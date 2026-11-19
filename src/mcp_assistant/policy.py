"""Permission policy: decides allow / ask-the-human / deny for every tool call.

Decision order for a tool:
  1. first matching rule in the profile's ``rules`` (glob on ``server__tool``)
  2. read-only tools         -> profile.read_only
  3. destructive tools       -> profile.destructive
  4. other state-changing    -> profile.non_read_only

Tools a profile denies outright are never even shown to the model (least privilege).
"""
from __future__ import annotations

import fnmatch
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .models import ToolInfo


class Decision(str, Enum):
    ALLOW = "allow"
    APPROVE = "approve"  # ask the human first
    DENY = "deny"


@dataclass
class Limits:
    max_steps: int = 8
    max_tool_calls_per_turn: int = 12
    max_cost_usd_per_turn: float = 0.25
    rate_limit_per_minute: int = 40
    max_result_chars: int = 8000
    max_history_messages: int = 40


@dataclass
class Policy:
    profile: str
    description: str
    read_only: Decision
    non_read_only: Decision
    destructive: Decision
    rules: list[tuple[str, Decision]]
    limits: Limits
    _calls: deque[float] = field(default_factory=deque, repr=False)

    @classmethod
    def load(cls, path: Path, profile: str = "standard") -> "Policy":
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        profiles = data.get("profiles", {})
        if profile not in profiles:
            raise ValueError(f"Unknown profile '{profile}'. Available: {', '.join(profiles)}")
        p = profiles[profile]
        return cls(
            profile=profile,
            description=p.get("description", ""),
            read_only=Decision(p.get("read_only", "allow")),
            non_read_only=Decision(p.get("non_read_only", "approve")),
            destructive=Decision(p.get("destructive", "approve")),
            rules=[(r["match"], Decision(r["action"])) for r in p.get("rules", [])],
            limits=Limits(**data.get("limits", {})),
        )

    @staticmethod
    def profiles(path: Path) -> list[str]:
        return list(yaml.safe_load(path.read_text(encoding="utf-8")).get("profiles", {}))

    def decide(self, tool: ToolInfo) -> tuple[Decision, str]:
        for pattern, decision in self.rules:
            if fnmatch.fnmatch(tool.qualified, pattern):
                return decision, f"rule '{pattern}'"
        if tool.read_only:
            return self.read_only, "read-only tool"
        if tool.destructive:
            return self.destructive, "destructive tool"
        return self.non_read_only, "state-changing tool"

    def exposed(self, tool: ToolInfo) -> bool:
        return self.decide(tool)[0] is not Decision.DENY

    def rate_ok(self) -> bool:
        """Sliding-window rate limit over the last 60 seconds. Records the call if allowed."""
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) >= self.limits.rate_limit_per_minute:
            return False
        self._calls.append(now)
        return True
