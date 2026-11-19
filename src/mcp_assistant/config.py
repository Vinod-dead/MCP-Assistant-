"""Paths and environment helpers shared by the host and the MCP servers.

Important: ``load_env()`` is only ever called by the *host* (CLI / eval). MCP servers run
as child processes and receive only the environment variables listed for them in
``config/mcp_servers.json`` -- they never see your other secrets.
"""
from __future__ import annotations

import os
from pathlib import Path


def _find_root() -> Path:
    env = os.environ.get("MCP_ASSISTANT_HOME")
    if env:
        return Path(env).resolve()
    for cand in (Path(__file__).resolve().parents[2], Path.cwd()):
        if (cand / "config" / "mcp_servers.json").exists():
            return cand
    return Path.cwd()


ROOT = _find_root()


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return (Path(value).expanduser() if value else default).resolve()


def data_dir() -> Path:
    d = _path_from_env("MCP_ASSISTANT_DATA", ROOT / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = _path_from_env("MCP_ASSISTANT_LOGS", ROOT / "logs")
    d.mkdir(parents=True, exist_ok=True)
    return d


def files_root() -> Path:
    return _path_from_env("FILES_ROOT", ROOT / "workspace")


def repo_root() -> Path:
    return _path_from_env("REPO_ROOT", ROOT)


def db_url() -> str:
    return os.environ.get("DATABASE_URL") or f"sqlite:///{(data_dir() / 'business.db').as_posix()}"


def load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

def have_gemini_credentials() -> bool:
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return True
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes"}


def have_nvidia_credentials() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY"))