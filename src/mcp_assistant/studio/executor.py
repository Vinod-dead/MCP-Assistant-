"""Governed tool execution for the dashboard (manual runs and read-only views).

Same rules as the agent loop: policy decision -> human approval -> real MCP call -> redaction ->
injection scan -> audit. The browser can never call a tool without going through here.
"""
from __future__ import annotations

import time
from typing import Any

from ..policy import Decision
from ..security import injection_scan, redact_args, redact_secrets
from .state import CALL_SOURCE, StudioState

MAX_MANUAL_OUTPUT = 20_000


async def governed_call(state: StudioState, name: str, args: dict[str, Any], *, source: str = "manual") -> dict[str, Any]:
    rt = state.runtime
    info = rt.hub.tools.get(name)
    base = {"tool": name, "args": redact_args(args), "source": source}

    def refuse(status: str, message: str, **extra: Any) -> dict[str, Any]:
        rt.audit.write(event="tool_call", status=status, **base, **extra)
        return {"ok": False, "status": status, "output": message, "ms": 0, "flags": [], "decision": extra.get("decision")}

    if info is None:
        return refuse("unknown_tool", f"Unknown tool '{name}'.")
    decision, why = rt.policy.decide(info)
    if decision is Decision.DENY:
        return refuse("denied", f"Blocked by policy ({why}, profile '{rt.policy.profile}').", decision="deny", reason=why)
    if not rt.policy.rate_ok():
        return refuse("rate_limited", "Rate limit reached; wait a moment.")

    approved: bool | None = None
    if decision is Decision.APPROVE:
        approved = await state.approvals.request(info, args, source=source, conversation_id=None, announce=None)
        if not approved:
            return refuse("declined", "You declined (or the request expired).", decision="approve", reason=why)

    token = CALL_SOURCE.set(source)
    t0 = time.perf_counter()
    try:
        text, is_error = await rt.hub.call(name, args)
    finally:
        CALL_SOURCE.reset(token)
    elapsed = round((time.perf_counter() - t0) * 1000)
    text = redact_secrets(text)
    flags = injection_scan(text)
    if len(text) > MAX_MANUAL_OUTPUT:
        text = text[:MAX_MANUAL_OUTPUT] + f"\n…[output truncated at {MAX_MANUAL_OUTPUT:,} characters]"
    status = "error" if is_error else "ok"
    rt.audit.write(event="tool_call", status=status, **base, decision=decision.value, approved=approved, ms=elapsed,
                   chars=len(text), injection_flags=flags)
    return {"ok": not is_error, "status": status, "output": text, "ms": elapsed, "flags": flags, "decision": decision.value}


async def read_tool(state: StudioState, name: str, args: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Convenience for dashboard reads (file tree, git status...). Returns (ok, text)."""
    res = await governed_call(state, name, args or {}, source="explorer")
    return res["ok"], res["output"]
