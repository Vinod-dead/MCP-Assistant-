"""MCP hub: starts every configured MCP server and exposes their tools as one flat catalogue.

Each server runs in its own long-lived task that owns the stdio transport, so servers start in
parallel and are shut down cleanly. Tool names are namespaced ``<server>__<tool>``.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import config
from .models import ToolInfo


def _expand(value: str) -> str:
    builtins = {"PYTHON": sys.executable, "ROOT": str(config.ROOT)}
    return re.sub(r"\$\{(\w+)\}", lambda m: builtins.get(m.group(1), os.environ.get(m.group(1), "")), value)


def load_server_params(path: Path, only: set[str] | None = None) -> dict[str, StdioServerParameters]:
    """Read an mcp_servers.json (Claude-Desktop / VS Code compatible shape) into stdio parameters."""
    raw = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    base_env = {"MCP_ASSISTANT_HOME": str(config.ROOT), "MCP_ASSISTANT_DATA": str(config.data_dir())}
    out: dict[str, StdioServerParameters] = {}
    for name, spec in raw.items():
        if spec.get("disabled") or (only and name not in only):
            continue
        env = {k: _expand(v) for k, v in (spec.get("env") or {}).items()}
        env = {k: v for k, v in env.items() if v != ""}  # unset vars are simply not passed
        out[name] = StdioServerParameters(
            command=_expand(spec["command"]),
            args=[_expand(a) for a in spec.get("args", [])],
            env={**base_env, **env},
        )
    return out


class ServerConnection:
    def __init__(self, name: str, params: StdioServerParameters) -> None:
        self.name = name
        self.params = params
        self.session: ClientSession | None = None
        self.tools: list[Any] = []
        self.error: str | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self, timeout: float = 45.0) -> bool:
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except asyncio.TimeoutError:
            self.error = self.error or "startup timed out"
        return self.error is None and self.session is not None

    async def _run(self) -> None:
        log_file = config.logs_dir() / f"server-{self.name}.log"
        try:
            with log_file.open("a", encoding="utf-8") as errlog:
                async with stdio_client(self.params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        self.tools = list(listed.tools)
                        self.session = session
                        self._ready.set()
                        await self._stop.wait()
        except Exception as exc:  # includes ExceptionGroup from the transport
            self.error = self.error or f"{type(exc).__name__}: {exc}"
        finally:
            self.session = None
            self._ready.set()

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, 10)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()


class MCPHub:
    def __init__(self) -> None:
        self.connections: dict[str, ServerConnection] = {}
        self.tools: dict[str, ToolInfo] = {}

    async def start(self, servers: dict[str, StdioServerParameters]) -> None:
        self.connections = {name: ServerConnection(name, p) for name, p in servers.items()}
        await asyncio.gather(*(c.start() for c in self.connections.values()))
        for conn in self.connections.values():
            self._register(conn)

    def _register(self, conn: "ServerConnection") -> None:
        for t in conn.tools:
            ann = t.annotations
            read_only = bool(getattr(ann, "read_only_hint", None))
            destructive = getattr(ann, "destructive_hint", None)
            open_world = getattr(ann, "open_world_hint", None)
            info = ToolInfo(
                server=conn.name,
                name=t.name,
                description=(t.description or "").strip(),
                input_schema=t.input_schema or {"type": "object", "properties": {}},
                read_only=read_only,
                # MCP spec defaults: not read-only => destructive and open-world unless said otherwise
                destructive=True if destructive is None else bool(destructive),
                open_world=True if open_world is None else bool(open_world),
            )
            self.tools[info.qualified] = info

    async def restart(self, name: str) -> tuple[bool, str | None]:
        """Stop and re-launch one server, then refresh its tools. Returns (running, error)."""
        old = self.connections.get(name)
        if old is None:
            raise KeyError(name)
        await old.stop()
        for qualified in [q for q, t in self.tools.items() if t.server == name]:
            del self.tools[qualified]
        conn = ServerConnection(name, old.params)
        self.connections[name] = conn
        ok = await conn.start()
        self._register(conn)
        return ok, conn.error

    def status(self) -> list[tuple[str, bool, int, str | None]]:
        return [(n, c.session is not None, len(c.tools), c.error) for n, c in self.connections.items()]

    async def call(self, qualified: str, args: dict[str, Any], timeout: float = 60.0) -> tuple[str, bool]:
        """Call a tool. Returns (text, is_error). Never raises for tool/server failures."""
        info = self.tools.get(qualified)
        conn = self.connections.get(info.server) if info else None
        if not info or not conn or not conn.session:
            return f"Tool '{qualified}' is not available (server not running).", True
        try:
            result = await conn.session.call_tool(info.name, args, read_timeout_seconds=timeout)
        except Exception as exc:
            return f"Tool call failed: {type(exc).__name__}: {exc}", True
        parts = [c.text if getattr(c, "type", "") == "text" else f"[{getattr(c, 'type', 'unknown')} content omitted]" for c in result.content]
        return "\n".join(parts), bool(result.is_error)

    async def close(self) -> None:
        await asyncio.gather(*(c.stop() for c in self.connections.values()), return_exceptions=True)
