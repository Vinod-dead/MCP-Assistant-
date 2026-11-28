"""Shared, long-lived state for the Studio API.

One MCP runtime (hub + policy + audit + metrics + agent) is created at startup and reused by every request.
Everything that has a lifecycle lives here: pending approvals, tool-execution statistics, LLM call records,
the conversation store and the single "one agent turn at a time" lock.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..models import LLMResponse, Message, ToolInfo
from ..runtime import Runtime, build_runtime, resolve_provider
from ..security import redact_secrets
from .store import ConversationStore

APPROVAL_TIMEOUT_S = 300
# Who triggered a tool call: "chat" (the agent), "manual" (MCP Tools page) or "explorer" (read-only dashboard views).
CALL_SOURCE: contextvars.ContextVar[str] = contextvars.ContextVar("call_source", default="chat")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ------------------------------------------------------------------------------ approvals
@dataclass
class Approval:
    id: str
    tool: str
    server: str
    description: str
    args: dict[str, Any]
    destructive: bool
    source: str
    conversation_id: str | None
    created: str = field(default_factory=now_iso)
    status: str = "pending"  # pending | approved | declined | expired
    decided: str | None = None
    future: asyncio.Future | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "tool": self.tool, "server": self.server, "description": self.description.split("\n")[0][:240],
            "args": self.args, "destructive": self.destructive, "source": self.source,
            "conversation_id": self.conversation_id, "created": self.created, "status": self.status,
            "decided": self.decided, "timeout_s": APPROVAL_TIMEOUT_S,
        }


class ApprovalManager:
    """Every state-changing tool call waits here for a human decision (chat card or global dialog)."""

    def __init__(self) -> None:
        self.pending: dict[str, Approval] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=200)

    async def request(self, info: ToolInfo, args: dict[str, Any], *, source: str, conversation_id: str | None,
                      announce: Callable[[dict[str, Any]], None] | None = None) -> bool:
        from ..security import redact_args

        item = Approval(uuid.uuid4().hex[:12], info.qualified, info.server, info.description, redact_args(args),
                        info.destructive, source, conversation_id, future=asyncio.get_running_loop().create_future())
        self.pending[item.id] = item
        if announce:
            announce({"type": "approval", **item.public()})
        try:
            allowed = bool(await asyncio.wait_for(item.future, APPROVAL_TIMEOUT_S))
            item.status = "approved" if allowed else "declined"
        except asyncio.TimeoutError:
            allowed, item.status = False, "expired"
        except asyncio.CancelledError:
            item.status = "declined"
            raise
        finally:
            item.decided = now_iso()
            self.pending.pop(item.id, None)
            self.history.appendleft(item.public())
        return allowed

    def resolve(self, approval_id: str, allow: bool) -> bool:
        item = self.pending.get(approval_id)
        if item is None or item.future is None or item.future.done():
            return False
        item.future.set_result(allow)
        return True

    def deny_for_conversation(self, conversation_id: str | None) -> None:
        for item in list(self.pending.values()):
            if item.source == "chat" and item.conversation_id == conversation_id and item.future and not item.future.done():
                item.future.set_result(False)

    def deny_all(self) -> None:
        for item in list(self.pending.values()):
            if item.future and not item.future.done():
                item.future.set_result(False)


# ------------------------------------------------------------------------------ statistics
class ToolStats:
    """Records every MCP call that goes through the hub (agent, manual runs, dashboard reads)."""

    def __init__(self) -> None:
        self.recent: deque[dict[str, Any]] = deque(maxlen=1000)
        self.by_tool: dict[str, dict[str, Any]] = {}
        self.by_server: dict[str, dict[str, Any]] = {}

    def record(self, tool: str, ok: bool, ms: int, chars: int, source: str, error: str | None = None, ts: str | None = None) -> None:
        server = tool.split("__", 1)[0]
        ts = ts or now_iso()
        entry = {"ts": ts, "tool": tool, "server": server, "ok": ok, "ms": ms, "chars": chars, "source": source,
                 "status": "ok" if ok else "error", "error": redact_secrets(error)[:300] if error else None}
        self.recent.appendleft(entry)
        t = self.by_tool.setdefault(tool, {"count": 0, "errors": 0, "last_ts": None, "last_ok": None, "last_ms": None, "last_error": None, "total_ms": 0})
        s = self.by_server.setdefault(server, {"count": 0, "errors": 0, "last_ok_ts": None, "last_error": None, "last_error_ts": None, "total_ms": 0})
        for agg in (t, s):
            agg["count"] += 1
            agg["total_ms"] += ms
            agg["errors"] += 0 if ok else 1
        t.update(last_ts=ts, last_ok=ok, last_ms=ms)
        if ok:
            s["last_ok_ts"] = ts
        else:
            t["last_error"] = entry["error"]
            s["last_error"], s["last_error_ts"] = entry["error"], ts

    def preload_from_audit(self, events: list[dict[str, Any]]) -> None:
        """Rebuild history after a restart from the append-only audit log (oldest first)."""
        for e in events:
            if e.get("event") != "tool_call" or e.get("status") not in {"ok", "error"}:
                continue
            self.record(e.get("tool", "?"), e["status"] == "ok", int(e.get("ms") or 0), int(e.get("chars") or 0),
                        e.get("source", "chat"), None, e.get("ts"))


class RecordingLLM:
    """Transparent wrapper that records success/latency/tokens of every model call (for Model Lab)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: deque[dict[str, Any]] = deque(maxlen=500)

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", "unknown")

    def __getattr__(self, item: str) -> Any:  # temperature, model, url, client, ...
        return getattr(self.inner, item)

    async def generate(self, system: str, messages: list[Message], tools: list[ToolInfo]) -> LLMResponse:
        t0 = time.perf_counter()
        try:
            resp = await self.inner.generate(system, messages, tools)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.calls.appendleft({"ts": now_iso(), "ok": False, "ms": round((time.perf_counter() - t0) * 1000),
                                   "input_tokens": 0, "output_tokens": 0, "error": redact_secrets(f"{type(exc).__name__}: {exc}")[:400]})
            raise
        self.calls.appendleft({"ts": now_iso(), "ok": True, "ms": round((time.perf_counter() - t0) * 1000),
                               "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens, "error": None})
        return resp

    async def close(self) -> None:
        closer = getattr(self.inner, "close", None)
        if closer:
            await closer()


# ------------------------------------------------------------------------------ studio state
@dataclass
class LiveConversation:
    """In-memory model history for one conversation (provider-level messages, replayed to the LLM)."""
    history: list[Message] = field(default_factory=list)
    marks: dict[str, int] = field(default_factory=dict)  # user message id -> history length before it


class StudioState:
    def __init__(self, *, provider: str = "auto", model: str | None = None, profile: str = "standard",
                 reflect: bool = False, dev_origins: tuple[str, ...] = ()) -> None:
        self.provider_arg, self.model_arg, self.profile, self.reflect = provider, model, profile, reflect
        self.startup_profile = profile
        self.dev_origins = dev_origins
        self.token = secrets.token_urlsafe(24)
        self.started = time.time()
        self.rt: Runtime | None = None
        self.llm: RecordingLLM | None = None
        self.approvals = ApprovalManager()
        self.stats = ToolStats()
        self.store: ConversationStore | None = None
        self.live: dict[str, LiveConversation] = {}
        self.turn_lock = asyncio.Lock()
        self.sink: Callable[[dict[str, Any]], None] | None = None
        self.active_conversation: str | None = None
        self.active_task: asyncio.Task | None = None
        self.stop_requested = False
        self.last_playground: dict[str, Any] | None = None

    # -- agent callbacks -----------------------------------------------------------------
    def on_event(self, kind: str, data: dict[str, Any]) -> None:
        if self.sink is not None:
            self.sink({"type": kind, **data})

    async def chat_approver(self, info: ToolInfo, args: dict[str, Any]) -> bool:
        return await self.approvals.request(info, args, source="chat", conversation_id=self.active_conversation,
                                            announce=self.sink)

    # -- lifecycle ------------------------------------------------------------------------
    async def start(self) -> None:
        from ..demo_data import ensure_demo_data

        config.load_env()
        ensure_demo_data(config.data_dir())
        provider = resolve_provider(self.provider_arg)
        if provider == "nvidia" and not config.have_nvidia_credentials():
            raise RuntimeError("No NVIDIA credentials found. Put NVIDIA_API_KEY in .env (or start with --provider mock).")
        if provider == "gemini" and not config.have_gemini_credentials():
            raise RuntimeError("No Gemini credentials found. Put GEMINI_API_KEY in .env (or start with --provider mock).")
        import os

        env_model = os.environ.get("NVIDIA_MODEL") if provider == "nvidia" else os.environ.get("GEMINI_MODEL")
        self.rt = await build_runtime(provider=provider, model=self.model_arg or env_model, profile=self.profile,
                                      approver=self.chat_approver, on_event=self.on_event, reflect=self.reflect)
        self.llm = RecordingLLM(self.rt.agent.llm)
        self.rt.agent.llm = self.llm  # type: ignore[assignment]

        hub = self.rt.hub
        original_call = hub.call

        async def recording_call(qualified: str, args: dict[str, Any], timeout: float = 60.0) -> tuple[str, bool]:
            t0 = time.perf_counter()
            text, is_error = await original_call(qualified, args, timeout)
            self.stats.record(qualified, not is_error, round((time.perf_counter() - t0) * 1000), len(text),
                              CALL_SOURCE.get(), text if is_error else None)
            return text, is_error

        hub.call = recording_call  # type: ignore[method-assign]
        self.stats.preload_from_audit(list(reversed(self.rt.audit.tail(2000))))
        self.store = ConversationStore(config.data_dir() / "studio" / "conversations")

    async def stop(self) -> None:
        self.approvals.deny_all()
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
        if self.llm:
            try:
                await self.llm.close()
            except Exception:
                pass
        if self.rt:
            await self.rt.close()

    # -- helpers ---------------------------------------------------------------------------
    @property
    def runtime(self) -> Runtime:
        assert self.rt is not None, "runtime not started"
        return self.rt

    def logs_path(self, name: str) -> Path:
        return config.logs_dir() / name

    def audit_write(self, **fields: Any) -> None:
        self.runtime.audit.write(**fields)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
