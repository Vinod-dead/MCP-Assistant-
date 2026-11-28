"""FastAPI application factory for MCP Assistant Studio.

One process: the Python MCP runtime, this JSON/SSE API, and the pre-built Next.js dashboard (served from
``studio/web``). For frontend development run ``npm run dev`` in ``frontend/`` and start this with ``--dev``.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__, config
from . import routes_chat, routes_data, routes_system
from .dbx import DatabaseExplorer
from .state import StudioState

WEB_DIR = Path(__file__).parent / "web"
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}
DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
log = logging.getLogger("mcp_assistant.studio")

FALLBACK_HTML = """<!doctype html><meta charset=utf-8><title>MCP Assistant Studio</title>
<body style="font:16px system-ui;background:#0b0d12;color:#e6e8ef;max-width:640px;margin:12vh auto;padding:0 20px">
<h1>MCP Assistant Studio API is running</h1>
<p>The dashboard has not been built yet. Run <code>npm install &amp;&amp; npm run build</code> in <code>frontend/</code>,
then <code>python scripts/sync_frontend.py</code> (copies the build into <code>src/mcp_assistant/studio/web</code>) and reload.</p>
<p>API docs: <a style="color:#8ab4ff" href="/api/docs">/api/docs</a></p></body>"""


def _hostname(host: str) -> str:
    return host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]


class HostGuard:
    """Reject requests whose Host header is not localhost -- defeats DNS-rebinding attacks on a local server."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in {"http", "websocket"}:
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
            if _hostname(host) not in LOOPBACK:
                if scope["type"] == "http":
                    await JSONResponse({"error": "Host not allowed"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(*, provider: str = "auto", model: str | None = None, profile: str = "standard", reflect: bool = False,
               dev: bool = False) -> FastAPI:
    state = StudioState(provider=provider, model=model, profile=profile, reflect=reflect, dev_origins=DEV_ORIGINS if dev else ())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await state.start()
        app.state.dbx = DatabaseExplorer(config.data_dir() / "studio" / "sql_history.json")
        # One dedicated thread for all explorer queries: SQLite connections must be created and closed on the same thread.
        app.state.db_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db-explorer")
        try:
            yield
        finally:
            app.state.db_pool.shutdown(wait=False, cancel_futures=True)
            await state.stop()

    app = FastAPI(title="MCP Assistant Studio API", version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.studio = state

    if dev:
        app.add_middleware(CORSMiddleware, allow_origins=list(DEV_ORIGINS), allow_methods=["GET", "POST", "DELETE"],
                           allow_headers=["Content-Type", "X-Session-Token"])
    app.add_middleware(HostGuard)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail if isinstance(exc.detail, str) else str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse({"error": f"Invalid request: {where} {first.get('msg', '')}".strip()}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"error": f"Internal error: {type(exc).__name__}"}, status_code=500)

    app.include_router(routes_system.public)
    app.include_router(routes_system.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_data.router)

    if (WEB_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        async def fallback() -> HTMLResponse:
            return HTMLResponse(FALLBACK_HTML)

    return app
