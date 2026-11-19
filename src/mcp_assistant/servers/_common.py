"""Helpers shared by every MCP server (sandboxing, SSRF guard, tool annotations).

NOTE: MCP stdio servers must never write to stdout -- it carries the protocol. Use stderr.
"""
from __future__ import annotations

import functools
import ipaddress
import json
import logging
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..security import redact_secrets

# Tool annotations drive the permission policy on the host side.
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
READ_EXTERNAL = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
WRITE_EXTERNAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class _Server(MCPServer):
    """MCPServer whose tools turn *any* failure into a readable (redacted, truncated) ToolError.

    MCP 2.x hides unexpected exception text from clients. These servers are local and trusted, and the
    model needs messages like "unknown table" or "path outside folder" to correct itself, so we surface
    them -- after secret redaction -- and log the traceback to the server's stderr log.
    """

    def tool(self, *args: Any, **kwargs: Any):
        register = super().tool(*args, **kwargs)

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*a: Any, **k: Any):
                try:
                    return fn(*a, **k)
                except ToolError:
                    raise
                except ValueError as exc:  # our own validation errors: message is already user-facing
                    raise ToolError(redact_secrets(str(exc))[:800]) from exc
                except Exception as exc:
                    logging.getLogger("mcp_assistant").exception("tool %s failed", fn.__name__)
                    raise ToolError(redact_secrets(f"{type(exc).__name__}: {exc}")[:800]) from exc

            register(wrapper)
            return fn  # return the original so unit tests can call tools directly

        return decorator


def make_server(name: str, instructions: str = "") -> MCPServer:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    return _Server(name, instructions=instructions, log_level="WARNING")


def to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def truncate(text: str, limit: int, note: str = "\n…[truncated]") -> str:
    return text if len(text) <= limit else text[:limit] + note


# ------------------------------------------------------------------ filesystem sandbox
BLOCKED_NAMES = {".env", ".env.local", ".netrc", "id_rsa", "id_ed25519", "credentials.json", "service-account.json", ".npmrc"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
EXECUTABLE_SUFFIXES = {".exe", ".bat", ".cmd", ".ps1", ".sh", ".py", ".js", ".dll", ".so", ".msi", ".jar"}


def resolve_in_root(root: Path, rel: str) -> Path:
    """Resolve ``rel`` inside ``root``; reject traversal, absolute escapes and symlink escapes."""
    root = root.resolve()
    target = (root / rel).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError("Path is outside the allowed folder.")
    return target


def assert_not_secret(path: Path) -> None:
    if path.name.lower() in BLOCKED_NAMES or path.suffix.lower() in BLOCKED_SUFFIXES:
        raise ValueError("Access to credential/secret files is blocked.")


# ----------------------------------------------------------------------- network guard
def assert_public_url(url: str, allow_hosts: set[str] | None = None, allow_private: bool = False) -> str:
    """Block SSRF: only http(s), optional host allowlist, and no private/loopback/link-local IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute http(s) URLs are allowed.")
    host = parsed.hostname.lower()
    if allow_hosts is not None and host not in allow_hosts:
        raise ValueError(f"Host '{host}' is not on the allowlist (API_ALLOWLIST).")
    if not allow_private:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ValueError(f"Cannot resolve host '{host}'.") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise ValueError("Requests to private or internal addresses are blocked.")
    return url


def safe_request(
    method: str,
    url: str,
    *,
    allow_hosts: set[str] | None = None,
    allow_private: bool = False,
    max_redirects: int = 3,
    timeout: float = 20.0,
    **kwargs: Any,
) -> httpx.Response:
    """httpx request that re-validates every redirect hop against the SSRF guard."""
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            assert_public_url(url, allow_hosts, allow_private)
            resp = client.request(method, url, **kwargs)
            if resp.is_redirect and resp.headers.get("location"):
                url = urljoin(url, resp.headers["location"])
                if resp.status_code in (301, 302, 303):
                    method, kwargs = "GET", {k: v for k, v in kwargs.items() if k in {"headers", "params"}}
                continue
            return resp
    raise ValueError("Too many redirects.")
