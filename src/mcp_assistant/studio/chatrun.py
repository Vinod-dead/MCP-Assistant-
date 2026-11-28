"""Runs one agent turn and streams its *real* execution events (server-sent events) to the browser.

Event types: start, token, llm_start, llm_call, tool_call, tool_result, tool_blocked, approval,
reflection, done, stopped, error.  Everything except `token` is persisted with the assistant message so a
reloaded conversation shows exactly what happened.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import asdict
from typing import Any, AsyncIterator

from ..models import Message
from .state import LiveConversation, StudioState, dumps, now_iso
from .store import MAX_STEP_OUTPUT

HEARTBEAT_S = 15


def sse(obj: dict[str, Any]) -> str:
    return f"data: {dumps(obj)}\n\n"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def title_from(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:57] + "…") if len(t) > 58 else (t or "New conversation")


def ensure_live(state: StudioState, conv: dict[str, Any]) -> LiveConversation:
    """Model-level history for a conversation; rebuilt from stored text after a server restart."""
    live = state.live.get(conv["id"])
    if live is not None:
        return live
    live = LiveConversation()
    msgs = conv.get("messages", [])
    for i, m in enumerate(msgs):
        if m["role"] == "user":
            live.marks[m["id"]] = len(live.history)
            live.history.append(Message("user", text=m["content"]))
        elif m["role"] == "assistant":
            if m.get("status") == "done":
                live.history.append(Message("model", text=m["content"]))
            else:  # failed / stopped turns were rolled back when they happened
                prev_user = next((x for x in reversed(msgs[:i]) if x["role"] == "user"), None)
                if prev_user and prev_user["id"] in live.marks:
                    del live.history[live.marks[prev_user["id"]]:]
    state.live[conv["id"]] = live
    return live


def _compact(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in steps:
        s = dict(s)
        if isinstance(s.get("output"), str) and len(s["output"]) > MAX_STEP_OUTPUT:
            s["output"] = s["output"][:MAX_STEP_OUTPUT] + "\n…[truncated for storage]"
        out.append(s)
    return out


def _metrics(turn: Any) -> dict[str, Any]:
    if turn is None:
        return {}
    d = asdict(turn)
    for k in ("spans", "started", "question"):
        d.pop(k, None)
    d["tokens_per_sec"] = round(turn.tokens_per_sec, 1)
    d["wall_seconds"] = round(turn.wall_seconds, 3)
    d["summary"] = turn.summary()
    return d


async def chat_stream(state: StudioState, conv: dict[str, Any], text: str, *, regenerate: bool = False) -> AsyncIterator[str]:
    async with state.turn_lock:
        rt = state.runtime
        agent = rt.agent
        live = ensure_live(state, conv)
        msgs: list[dict[str, Any]] = conv["messages"]

        if regenerate:
            while msgs and msgs[-1]["role"] != "user":
                msgs.pop()
            user_msg = msgs[-1]
            text = user_msg["content"]
            del live.history[live.marks.get(user_msg["id"], len(live.history)):]
        else:
            user_msg = {"id": new_id(), "role": "user", "content": text, "ts": now_iso()}
            msgs.append(user_msg)
            if sum(1 for m in msgs if m["role"] == "user") == 1:
                conv["title"] = title_from(text)
            live.marks[user_msg["id"]] = len(live.history)
        state.store.save(conv)  # the user's message is never lost, even if the turn fails

        agent.history = live.history
        state.active_conversation = conv["id"]
        state.stop_requested = False
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        steps: list[dict[str, Any]] = []
        t_start = time.perf_counter()
        live_text = {"value": ""}

        def stamp(ev: dict[str, Any]) -> dict[str, Any]:
            return {**ev, "ts": now_iso(), "t_ms": round((time.perf_counter() - t_start) * 1000)}

        def sink(ev: dict[str, Any]) -> None:
            ev = stamp(ev)
            if ev["type"] == "llm_start":
                live_text["value"] = ""
            steps.append(ev)
            queue.put_nowait(ev)

        inner = state.llm.inner if state.llm else None
        streaming = inner is not None and hasattr(inner, "on_token")

        def on_token(piece: str) -> None:
            live_text["value"] += piece
            queue.put_nowait({"type": "token", "text": piece})

        state.sink = sink
        if streaming:
            inner.on_token = on_token  # type: ignore[union-attr]
        task = asyncio.create_task(agent.run_turn(text), name="agent-turn")
        state.active_task = task
        task.add_done_callback(lambda _t: queue.put_nowait(None))
        assistant_id = new_id()

        def sync_history(roll_back: bool) -> None:
            """The agent may re-create its history list (trimming), so copy it back and fix this turn's mark."""
            live.history = agent.history
            idx = next((i for i in range(len(live.history) - 1, -1, -1)
                        if live.history[i].role == "user" and live.history[i].text == text), None)
            if roll_back and idx is not None:
                del live.history[idx:]
                idx = None
            live.marks[user_msg["id"]] = idx if idx is not None else len(live.history)
            agent.history = live.history

        def finish_stopped() -> dict[str, Any]:
            sync_history(True)
            msg = {"id": assistant_id, "role": "assistant", "status": "stopped", "ts": now_iso(), "model": rt.model, "provider": rt.provider,
                   "content": live_text["value"].strip() or "Generation stopped.", "steps": _compact(steps), "metrics": {}, "error": None}
            msgs.append(msg)
            state.store.save(conv)
            return msg

        try:
            yield sse(stamp({"type": "start", "conversation_id": conv["id"], "message_id": assistant_id, "title": conv["title"],
                             "model": rt.model, "provider": rt.provider, "streaming": streaming, "regenerated": regenerate}))
            received = stamp({"type": "request_received"})
            steps.append(received)
            yield sse(received)
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev is None:
                    break
                yield sse(ev)

            if task.cancelled():
                yield sse(stamp({"type": "stopped", "message": finish_stopped(), "title": conv["title"]}))
                return
            result = task.result()
            sync_history(False)
            msg = {"id": assistant_id, "role": "assistant", "content": result.answer, "ts": now_iso(),
                   "status": "error" if result.error else "done", "error": result.error, "model": rt.model, "provider": rt.provider,
                   "steps": _compact(steps), "metrics": _metrics(result.metrics)}
            msgs.append(msg)
            state.store.save(conv)
            yield sse(stamp({"type": "done", "message": msg, "title": conv["title"]}))
        except asyncio.CancelledError:  # browser went away mid-turn: stop the agent and keep what happened
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(_settle(task)), 5)
            except Exception:
                pass
            finish_stopped()
            raise
        except Exception as exc:  # defensive: never leave the stream hanging
            sync_history(True)
            yield sse(stamp({"type": "error", "message": f"{type(exc).__name__}: {exc}"}))
        finally:
            state.approvals.deny_for_conversation(conv["id"])
            state.sink = None
            state.active_task = None
            state.active_conversation = None
            if inner is not None and streaming:
                inner.on_token = None  # type: ignore[union-attr]


async def _settle(task: asyncio.Task) -> None:
    try:
        await task
    except BaseException:
        pass
