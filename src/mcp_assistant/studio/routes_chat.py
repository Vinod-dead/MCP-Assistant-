"""Chat + conversations: streaming (SSE), stop, regenerate, history, search, clear."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .chatrun import chat_stream, ensure_live
from .deps import guard, studio

router = APIRouter(prefix="/api", dependencies=[Depends(guard)])
SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = None


def _load(state, conv_id: str) -> dict[str, Any]:
    conv = state.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found.")
    return conv


@router.post("/chat")
async def chat(body: ChatBody, request: Request) -> StreamingResponse:
    state = studio(request)
    if not body.message.strip():
        raise HTTPException(400, "Empty message.")
    if state.turn_lock.locked():
        raise HTTPException(409, "A request is already running. Stop it or wait for it to finish.")
    conv = _load(state, body.conversation_id) if body.conversation_id else state.store.create()
    return StreamingResponse(chat_stream(state, conv, body.message.strip()), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/conversations/{conv_id}/regenerate")
async def regenerate(conv_id: str, request: Request) -> StreamingResponse:
    state = studio(request)
    if state.turn_lock.locked():
        raise HTTPException(409, "A request is already running.")
    conv = _load(state, conv_id)
    if not any(m["role"] == "user" for m in conv["messages"]):
        raise HTTPException(400, "Nothing to regenerate.")
    return StreamingResponse(chat_stream(state, conv, "", regenerate=True), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat/stop")
async def stop(request: Request) -> dict[str, Any]:
    state = studio(request)
    task = state.active_task
    if task is None or task.done():
        return {"stopped": False}
    state.stop_requested = True
    state.approvals.deny_for_conversation(state.active_conversation)
    task.cancel()
    return {"stopped": True}


@router.get("/conversations")
async def conversations(request: Request, q: str = "") -> dict[str, Any]:
    return {"conversations": studio(request).store.list(q[:200])}


@router.post("/conversations")
async def create_conversation(request: Request) -> dict[str, Any]:
    return studio(request).store.create()


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, request: Request) -> dict[str, Any]:
    return _load(studio(request), conv_id)


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, request: Request) -> dict[str, Any]:
    state = studio(request)
    if state.turn_lock.locked() and state.active_conversation == conv_id:
        raise HTTPException(409, "This conversation is running.")
    _load(state, conv_id)
    state.store.delete(conv_id)
    state.live.pop(conv_id, None)
    return {"deleted": True}


@router.post("/conversations/{conv_id}/clear")
async def clear_conversation(conv_id: str, request: Request) -> dict[str, Any]:
    state = studio(request)
    if state.turn_lock.locked() and state.active_conversation == conv_id:
        raise HTTPException(409, "This conversation is running.")
    conv = _load(state, conv_id)
    conv["messages"] = []
    state.store.save(conv)
    state.live.pop(conv_id, None)
    return {"cleared": True}


@router.get("/conversations/{conv_id}/context")
async def conversation_context(conv_id: str, request: Request) -> dict[str, Any]:
    """What the model sees from this conversation (history) -- distinct from persistent memory."""
    state = studio(request)
    conv = _load(state, conv_id)
    live = ensure_live(state, conv)
    chars = sum(len(m.text) + sum(len(r.content) for r in m.tool_results) for m in live.history)
    return {"messages_in_context": len(live.history), "approx_tokens": chars // 4, "limit_messages": state.runtime.policy.limits.max_history_messages,
            "stored_messages": len(conv["messages"])}
