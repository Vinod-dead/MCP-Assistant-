"""Request guards. The dashboard can trigger real actions, so every /api call must prove it came from our own page."""
from __future__ import annotations

import asyncio
import secrets
from typing import Any, Callable

from fastapi import HTTPException, Request

from .state import StudioState


def studio(request: Request) -> StudioState:
    return request.app.state.studio


async def guard(request: Request) -> None:
    state = studio(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        same_origin = origin == f"{request.url.scheme}://{host}"
        if origin and not same_origin and origin not in state.dev_origins:
            raise HTTPException(403, "Cross-origin request rejected.")
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "Content-Type must be application/json.")
    if not secrets.compare_digest(request.headers.get("x-session-token", ""), state.token):
        raise HTTPException(401, "Missing or invalid session token.")


async def run_db(request: Request, fn: Callable[..., Any], *args: Any) -> Any:
    """Run blocking database-explorer work on the single dedicated DB thread."""
    return await asyncio.get_running_loop().run_in_executor(request.app.state.db_pool, fn, *args)
