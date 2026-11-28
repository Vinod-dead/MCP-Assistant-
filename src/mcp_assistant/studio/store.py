"""Conversation persistence: one small JSON file per conversation (atomic writes, id-validated paths)."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[a-f0-9]{12}$")
MAX_STEP_OUTPUT = 4000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConversationStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, conv_id: str) -> Path:
        if not _ID.match(conv_id):
            raise ValueError("invalid conversation id")
        return self.dir / f"{conv_id}.json"

    def create(self, title: str = "New conversation") -> dict[str, Any]:
        conv = {"id": uuid.uuid4().hex[:12], "title": title, "created": _now(), "updated": _now(), "messages": []}
        self.save(conv)
        return conv

    def get(self, conv_id: str) -> dict[str, Any] | None:
        try:
            path = self._path(conv_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, conv: dict[str, Any]) -> None:
        conv["updated"] = _now()
        path = self._path(conv["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(conv, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def delete(self, conv_id: str) -> bool:
        path = self._path(conv_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list(self, query: str = "") -> list[dict[str, Any]]:
        q = query.strip().lower()
        out: list[dict[str, Any]] = []
        for f in self.dir.glob("*.json"):
            try:
                conv = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            msgs = conv.get("messages", [])
            if q and q not in conv.get("title", "").lower() and not any(q in m.get("content", "").lower() for m in msgs):
                continue
            last = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
            out.append({
                "id": conv["id"], "title": conv.get("title", "Untitled"), "created": conv.get("created"), "updated": conv.get("updated"),
                "messages": len(msgs), "preview": (last or (msgs[-1] if msgs else {})).get("content", "")[:140],
                "tool_calls": sum(len([s for s in m.get("steps", []) if s.get("type") == "tool_call"]) for m in msgs),
            })
        return sorted(out, key=lambda c: c.get("updated") or "", reverse=True)
