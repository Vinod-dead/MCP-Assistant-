"""APIs MCP server -- call custom REST APIs, but only hosts you allowlist.

  API_ALLOWLIST=api.github.com,my-internal-api.example.com
  API_BEARER_TOKENS=api.github.com=ghp_xxx,my-internal-api.example.com=abc123

Tokens are injected here, on the server side -- the model never sees them.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from ._common import READ_EXTERNAL, WRITE_EXTERNAL, make_server, safe_request, truncate

mcp = make_server("api", "Call allowlisted REST APIs. GET is read-only; other methods need approval.")


def _allowlist() -> set[str]:
    return {h.strip().lower() for h in os.environ.get("API_ALLOWLIST", "").split(",") if h.strip()}


def _tokens() -> dict[str, str]:
    pairs = (p.split("=", 1) for p in os.environ.get("API_BEARER_TOKENS", "").split(",") if "=" in p)
    return {host.strip().lower(): tok.strip() for host, tok in pairs}


def _call(method: str, url: str, params: str, body: str) -> str:
    allow = _allowlist()
    if not allow:
        raise ValueError("No hosts are allowlisted. Set API_ALLOWLIST (comma-separated hostnames) in .env.")
    headers = {"Accept": "application/json", "User-Agent": "mcp-assistant/0.1"}
    token = _tokens().get((urlparse(url).hostname or "").lower())
    if token:
        headers["Authorization"] = f"Bearer {token}"
    kwargs: dict = {"headers": headers}
    if params:
        kwargs["params"] = json.loads(params)
    if body:
        kwargs["json"] = json.loads(body)
    resp = safe_request(
        method, url, allow_hosts=allow, allow_private=os.environ.get("API_ALLOW_PRIVATE", "").lower() == "true", **kwargs
    )
    return f"HTTP {resp.status_code}\n{truncate(resp.text, 8000)}"


@mcp.tool(annotations=READ_EXTERNAL)
def api_get(url: str, params_json: str = "") -> str:
    """GET a JSON API endpoint on an allowlisted host. `params_json` is an optional JSON object of query params."""
    return _call("GET", url, params_json, "")


@mcp.tool(annotations=WRITE_EXTERNAL)
def api_call(method: str, url: str, body_json: str = "", params_json: str = "") -> str:
    """POST/PUT/PATCH/DELETE on an allowlisted host. Needs human approval."""
    method = method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("method must be POST, PUT, PATCH or DELETE (use api_get for GET).")
    return _call(method, url, params_json, body_json)


if __name__ == "__main__":
    mcp.run()
