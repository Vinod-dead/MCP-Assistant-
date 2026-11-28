"""System-level endpoints: health, model, servers, tools, approvals, audit, security, analytics, settings."""
from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import __version__, config
from ..models import Message, ToolInfo
from ..policy import Decision, Policy
from ..security import _INJECTION_PATTERNS, _SECRET_PATTERNS
from . import analytics
from .deps import guard, run_db, studio
from .executor import governed_call
from .state import StudioState, now_iso

router = APIRouter(prefix="/api", dependencies=[Depends(guard)])
PROFILE_ORDER = {"readonly": 0, "standard": 1, "admin": 2}
BLOCKED_STATUSES = {"denied", "declined", "budget", "rate_limited", "unknown_tool"}


# ------------------------------------------------------------------------------ helpers
def tool_params(schema: dict[str, Any]) -> list[dict[str, Any]]:
    props = (schema or {}).get("properties", {}) or {}
    required = set((schema or {}).get("required", []) or [])
    out = []
    for name, spec in props.items():
        typ = spec.get("type")
        if typ is None and spec.get("anyOf"):
            typ = " | ".join(str(x.get("type", "any")) for x in spec["anyOf"])
        out.append({"name": name, "type": typ or "any", "required": name in required, "description": spec.get("description"),
                    "default": spec.get("default"), "enum": spec.get("enum")})
    return out


def tool_view(state: StudioState, t: ToolInfo) -> dict[str, Any]:
    decision, why = state.runtime.policy.decide(t)
    stats = state.stats.by_tool.get(t.qualified, {})
    return {
        "name": t.qualified, "server": t.server, "short": t.name, "description": t.description,
        "kind": "read" if t.read_only else ("destructive" if t.destructive else "write"),
        "permission": decision.value, "permission_reason": why, "exposed_to_model": decision is not Decision.DENY,
        "open_world": t.open_world, "params": tool_params(t.input_schema), "schema": t.input_schema,
        "stats": {"count": stats.get("count", 0), "errors": stats.get("errors", 0), "last_ts": stats.get("last_ts"),
                  "last_ok": stats.get("last_ok"), "last_ms": stats.get("last_ms"), "last_error": stats.get("last_error")},
    }


def server_view(state: StudioState) -> list[dict[str, Any]]:
    rt = state.runtime
    out = []
    for name, conn in rt.hub.connections.items():
        s = state.stats.by_server.get(name, {})
        args = list(conn.params.args or [])
        module = args[1] if len(args) > 1 and args[0] == "-m" else " ".join(args)
        out.append({
            "name": name, "status": "running" if conn.session is not None else "failed", "tools": len(conn.tools),
            "tool_names": sorted(t.name for t in conn.tools), "startup_error": conn.error, "module": module,
            "calls": s.get("count", 0), "errors": s.get("errors", 0),
            "avg_ms": round(s["total_ms"] / s["count"]) if s.get("count") else None,
            "last_ok_ts": s.get("last_ok_ts"), "last_error": s.get("last_error"), "last_error_ts": s.get("last_error_ts"),
        })
    return out


def read_events(state: StudioState, limit: int = 2000) -> list[dict[str, Any]]:
    return analytics.read_jsonl(state.runtime.audit.path, limit)


# ------------------------------------------------------------------------------ session / health
public = APIRouter(prefix="/api")


@public.get("/session")
async def session(request: Request) -> dict[str, Any]:
    """Bootstraps the per-run token. Same-origin only: no CORS headers are sent, so other sites cannot read it."""
    return {"token": studio(request).token, "version": __version__}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    state = studio(request)
    rt = state.runtime
    status = rt.hub.status()
    up = sum(1 for _, ok, _, _ in status if ok)
    db = await run_db(request, request.app.state.dbx.info)
    overall = "ok" if up == len(status) and db["connection"] == "connected" else ("degraded" if up else "down")
    return {"status": overall, "version": __version__, "uptime_s": round(time.time() - state.started), "provider": rt.provider, "model": rt.model,
            "offline_demo": rt.provider == "mock", "servers": {"up": up, "total": len(status)}, "tools": len(rt.hub.tools),
            "database": {"connection": db["connection"], "dialect": db["dialect"], "tables": db["table_count"]},
            "profile": rt.policy.profile, "busy": state.turn_lock.locked(), "pending_approvals": len(state.approvals.pending)}


# ------------------------------------------------------------------------------ model
@router.get("/model")
async def model(request: Request) -> dict[str, Any]:
    state = studio(request)
    rt, llm = state.runtime, state.llm
    inner = llm.inner if llm else None
    calls = list(llm.calls) if llm else []
    ok_calls = [c for c in calls if c["ok"]]
    p_in, p_out = rt.metrics._price()
    endpoint = None
    timeout = None
    if inner is not None and hasattr(inner, "url"):
        endpoint = str(inner.url).removesuffix("/chat/completions")
        try:
            timeout = inner.client.timeout.read
        except Exception:
            timeout = None
    last = calls[0] if calls else None
    return {
        "provider": rt.provider, "model": rt.model, "endpoint": endpoint, "timeout_s": timeout,
        "temperature": getattr(inner, "temperature", None), "streaming_supported": hasattr(inner, "on_token"),
        "credentials_configured": {"nvidia": config.have_nvidia_credentials(), "gemini": config.have_gemini_credentials()}.get(rt.provider, rt.provider == "mock"),
        "offline_demo": rt.provider == "mock",
        "connection": "not_tested" if not calls else ("ok" if last["ok"] else "error"),
        "last_call": last,
        "pricing_per_million": {"input": p_in, "output": p_out, "note": "Estimates from config/pricing.yaml; edit that file to match your real rates."},
        "usage": {
            "requests": len(calls), "successes": len(ok_calls), "success_rate": round(len(ok_calls) / len(calls), 3) if calls else None,
            "input_tokens": sum(c["input_tokens"] for c in ok_calls), "output_tokens": sum(c["output_tokens"] for c in ok_calls),
            "avg_latency_ms": round(sum(c["ms"] for c in ok_calls) / len(ok_calls)) if ok_calls else None,
            "est_cost_usd": round(sum(c["input_tokens"] * p_in + c["output_tokens"] * p_out for c in ok_calls) / 1e6, 6),
        },
        "recent_calls": calls[:30], "playground_last": state.last_playground,
    }


class PlaygroundBody(BaseModel):
    system: str = Field("You are a helpful assistant.", max_length=8000)
    prompt: str = Field(..., min_length=1, max_length=20000)
    temperature: float | None = Field(None, ge=0, le=2)


@router.post("/model/playground")
async def playground(body: PlaygroundBody, request: Request) -> dict[str, Any]:
    """Send one prompt straight to the model: no tools, no conversation history."""
    state = studio(request)
    if state.turn_lock.locked():
        raise HTTPException(409, "The assistant is busy with a chat request.")
    async with state.turn_lock:
        inner = state.llm.inner
        old_temp = getattr(inner, "temperature", None)
        if body.temperature is not None and old_temp is not None:
            inner.temperature = body.temperature
        t0 = time.perf_counter()
        try:
            resp = await state.llm.generate(body.system, [Message("user", text=body.prompt)], [])
            ms = round((time.perf_counter() - t0) * 1000)
            p_in, p_out = state.runtime.metrics._price()
            result = {"ok": True, "text": resp.text, "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                      "latency_ms": ms, "est_cost_usd": round((resp.usage.input_tokens * p_in + resp.usage.output_tokens * p_out) / 1e6, 6),
                      "tokens_per_sec": round(resp.usage.output_tokens / (ms / 1000), 1) if ms >= 50 and resp.usage.output_tokens else None,
                      "error": None, "temperature": getattr(inner, "temperature", None), "model": state.runtime.model}
        except Exception as exc:
            result = {"ok": False, "text": "", "input_tokens": 0, "output_tokens": 0, "latency_ms": round((time.perf_counter() - t0) * 1000),
                      "est_cost_usd": 0, "tokens_per_sec": None, "error": f"{type(exc).__name__}: {exc}"[:1500], "temperature": old_temp, "model": state.runtime.model}
        finally:
            if old_temp is not None:
                inner.temperature = old_temp
        state.last_playground = {"ts": now_iso(), **{k: v for k, v in result.items() if k != "text"}}
        return result


@router.post("/model/test")
async def model_test(request: Request) -> dict[str, Any]:
    return await playground(PlaygroundBody(system="Reply with the single word OK.", prompt="ping", temperature=0), request)


# ------------------------------------------------------------------------------ servers
@router.get("/servers")
async def servers(request: Request, probe: bool = False) -> dict[str, Any]:
    state = studio(request)
    items = server_view(state)
    if probe:  # active liveness check: MCP ping, with a short timeout
        async def ping(item: dict[str, Any]) -> None:
            conn = state.runtime.hub.connections[item["name"]]
            if conn.session is None:
                item["responsive"] = False
                return
            t0 = time.perf_counter()
            try:
                await asyncio.wait_for(conn.session.send_ping(), 3)
                item["responsive"], item["ping_ms"] = True, round((time.perf_counter() - t0) * 1000)
            except Exception:
                item["responsive"] = False
        await asyncio.gather(*(ping(i) for i in items))
    return {"servers": items, "probed": probe}


@router.post("/servers/{name}/restart")
async def restart_server(name: str, request: Request) -> dict[str, Any]:
    state = studio(request)
    if name not in state.runtime.hub.connections:
        raise HTTPException(404, f"Unknown server '{name}'.")
    if state.turn_lock.locked():
        raise HTTPException(409, "Wait for the running chat request to finish before restarting a server.")
    async with state.turn_lock:
        running, error = await state.runtime.hub.restart(name)
    state.audit_write(event="server_restart", status="ok" if running else "error", server=name, error=error)
    return {"name": name, "running": running, "error": error, "tools": sum(1 for t in state.runtime.hub.tools.values() if t.server == name)}


# ------------------------------------------------------------------------------ tools
@router.get("/tools")
async def tools(request: Request) -> dict[str, Any]:
    state = studio(request)
    views = sorted((tool_view(state, t) for t in state.runtime.hub.tools.values()), key=lambda t: t["name"])
    return {"tools": views, "total": len(views), "exposed": sum(1 for t in views if t["exposed_to_model"]),
            "servers": sorted({t["server"] for t in views})}


class ExecuteBody(BaseModel):
    name: str = Field(..., max_length=120)
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/tools/execute")
async def execute_tool(body: ExecuteBody, request: Request) -> dict[str, Any]:
    """Run one real MCP tool with the same policy / approval / redaction / audit as the agent."""
    state = studio(request)
    if state.turn_lock.locked() and body.name not in state.runtime.hub.tools:
        raise HTTPException(409, "busy")
    return await governed_call(state, body.name, body.args, source="manual")


@router.get("/tools/history")
async def tool_history(request: Request, limit: int = 100, tool: str | None = None, source: str | None = None) -> dict[str, Any]:
    state = studio(request)
    items = [e for e in state.stats.recent if (not tool or e["tool"] == tool) and (not source or e["source"] == source)]
    return {"executions": items[: max(1, min(limit, 500))]}


# ------------------------------------------------------------------------------ approvals
@router.get("/approvals")
async def approvals(request: Request) -> dict[str, Any]:
    state = studio(request)
    return {"pending": [a.public() for a in state.approvals.pending.values()], "history": list(state.approvals.history)[:50]}


class DecisionBody(BaseModel):
    allow: bool


@router.post("/approvals/{approval_id}")
async def decide_approval(approval_id: str, body: DecisionBody, request: Request) -> dict[str, Any]:
    if not studio(request).approvals.resolve(approval_id, body.allow):
        raise HTTPException(404, "No such pending approval (it may have expired).")
    return {"ok": True}


# ------------------------------------------------------------------------------ audit / security
@router.get("/audit")
async def audit(request: Request, limit: int = 100, status: str | None = None, tool: str | None = None, event: str | None = None) -> dict[str, Any]:
    state = studio(request)
    events = read_events(state, 5000)
    events = [e for e in events if (not status or e.get("status") == status) and (not tool or tool in str(e.get("tool", "")))
              and (not event or e.get("event") == event)]
    return {"events": list(reversed(events[-max(1, min(limit, 500)):])), "total": len(events), "path": "logs/audit.jsonl"}


@router.get("/security")
async def security(request: Request) -> dict[str, Any]:
    state = studio(request)
    rt = state.runtime
    pol = rt.policy
    counts = {"allow": 0, "approve": 0, "deny": 0}
    for t in rt.hub.tools.values():
        counts[pol.decide(t)[0].value] += 1
    events = read_events(state, 3000)
    sec_events = []
    for e in reversed(events):
        reasons = []
        if e.get("injection_flags"):
            reasons.append("prompt-injection heuristics: " + ", ".join(e["injection_flags"]))
        if e.get("status") in BLOCKED_STATUSES:
            reasons.append(f"blocked ({e['status']})")
        if e.get("status") == "error":
            reasons.append("tool error")
        if e.get("event") in {"turn_error", "policy_change", "server_restart"}:
            reasons.append(e["event"])
        if reasons:
            sec_events.append({"ts": e.get("ts"), "tool": e.get("tool"), "status": e.get("status"), "event": e.get("event"), "reasons": reasons,
                               "source": e.get("source", "chat")})
        if len(sec_events) >= 60:
            break
    write_tool = rt.hub.tools.get("db__execute_write")
    return {
        "profile": pol.profile, "description": pol.description, "startup_profile": state.startup_profile,
        "decisions": {"read_only": pol.read_only.value, "state_changing": pol.non_read_only.value, "destructive": pol.destructive.value},
        "rules": [{"match": m, "action": d.value} for m, d in pol.rules], "limits": asdict(pol.limits), "tool_permissions": counts,
        "redaction": {"enabled": True, "secret_patterns": len(_SECRET_PATTERNS), "applies_to": ["tool output before the model sees it", "audit log arguments", "dashboard views"]},
        "injection_scan": {"enabled": True, "patterns": len(_INJECTION_PATTERNS)},
        "database": {"read_only_connection": True, "sql_guard": "single SELECT/WITH/EXPLAIN statement; forbidden keywords blocked",
                     "write_tool": None if write_tool is None else {"name": write_tool.qualified, "permission": pol.decide(write_tool)[0].value}},
        "approvals": {"pending": [a.public() for a in state.approvals.pending.values()], "history": list(state.approvals.history)[:50]},
        "security_events": sec_events, "audit_events_total": len(events),
        "failed_operations": [e for e in reversed(events) if e.get("status") in {"error"} or e.get("event") == "turn_error"][:30],
    }


# ------------------------------------------------------------------------------ analytics / overview
@router.get("/analytics")
async def analytics_view(request: Request) -> dict[str, Any]:
    state = studio(request)
    data = analytics.build(state.logs_path("traces.jsonl"), state.runtime.audit.path)
    data["session"] = state.runtime.metrics.session_summary()
    return data


@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    state = studio(request)
    rt = state.runtime
    h = await health(request)
    a = analytics.build(state.logs_path("traces.jsonl"), rt.audit.path)
    totals = a["totals"]
    recent_runs = [e for e in state.stats.recent if e["source"] in {"chat", "manual"}][:8]
    events = read_events(state, 400)
    db_calls = [e for e in state.stats.recent if e["tool"].startswith("db__")]
    return {
        "health": h,
        "cards": {"requests": totals["requests"], "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
                  "avg_latency_s": totals["avg_latency_s"], "cost_usd": totals["cost_usd"], "tool_success_rate": totals["tool_success_rate"],
                  "tools_total": len(rt.hub.tools), "tools_exposed": sum(1 for t in rt.hub.tools.values() if rt.policy.exposed(t))},
        "recent_conversations": state.store.list()[:5], "recent_tool_runs": recent_runs, "servers": server_view(state),
        "database": {**await run_db(request, request.app.state.dbx.info), "recent_queries": request.app.state.dbx.history(5),
                     "mcp_db_calls": len(db_calls), "recent_mcp_db_calls": db_calls[:5]},
        "token_series": [{"index": r["index"], "ts": r["ts"], "input": r["input_tokens"], "output": r["output_tokens"]} for r in a["requests"][-30:]],
        "recent_audit": list(reversed(events[-8:])),
    }


# ------------------------------------------------------------------------------ settings
ENV_FLAGS = ["NVIDIA_API_KEY", "NVIDIA_MODEL", "NVIDIA_BASE_URL", "GEMINI_API_KEY", "DATABASE_URL", "FILES_ROOT", "REPO_ROOT", "GITHUB_TOKEN",
             "SLACK_BOT_TOKEN", "NOTION_TOKEN", "GMAIL_ADDRESS", "GOOGLE_CLOUD_PROJECT", "AWS_ACCESS_KEY_ID", "AZURE_STORAGE_CONNECTION_STRING", "APPS_DRY_RUN"]


@router.get("/settings")
async def settings(request: Request) -> dict[str, Any]:
    state = studio(request)
    rt = state.runtime
    policy_path = config.ROOT / "config" / "policy.yaml"
    profiles = []
    for name in Policy.profiles(policy_path):
        p = Policy.load(policy_path, name)
        profiles.append({"name": name, "description": p.description, "read_only": p.read_only.value, "state_changing": p.non_read_only.value, "destructive": p.destructive.value})
    return {
        "profile": rt.policy.profile, "startup_profile": state.startup_profile, "profiles": profiles,
        "can_switch_to": [n for n in PROFILE_ORDER if PROFILE_ORDER[n] <= PROFILE_ORDER.get(state.startup_profile, 1) and n != rt.policy.profile],
        "limits": asdict(rt.policy.limits), "reflect": state.reflect,
        "environment": {k: bool(os.environ.get(k)) for k in ENV_FLAGS},  # booleans only -- values are never sent to the browser
        "paths": {"files_root": str(config.files_root()), "repo_root": str(config.repo_root()), "data": str(config.data_dir()), "logs": str(config.logs_dir())},
        "runtime": {"version": __version__, "python": sys.version.split()[0], "platform": platform.platform(terse=True), "provider": rt.provider, "model": rt.model},
    }


class ProfileBody(BaseModel):
    profile: str


@router.post("/settings/profile")
async def switch_profile(body: ProfileBody, request: Request) -> dict[str, Any]:
    """Privileges can be *lowered* at runtime. Raising them above the profile the server was started with needs a restart."""
    state = studio(request)
    rt = state.runtime
    if body.profile not in PROFILE_ORDER:
        raise HTTPException(400, "Unknown profile.")
    if PROFILE_ORDER[body.profile] > PROFILE_ORDER.get(state.startup_profile, 1):
        raise HTTPException(403, f"Starting profile is '{state.startup_profile}'. Restart with --profile {body.profile} to raise privileges.")
    if state.turn_lock.locked():
        raise HTTPException(409, "Wait for the running chat request to finish.")
    new = Policy.load(config.ROOT / "config" / "policy.yaml", body.profile)
    old = rt.policy.profile
    rt.policy = new
    rt.agent.policy = new
    state.audit_write(event="policy_change", status="ok", **{"from": old, "to": body.profile})
    return {"profile": body.profile}
