
"""Wiring: build a ready-to-use Agent (hub + policy + audit + metrics + memory + LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import os
from . import config
from .agent import Agent, Approver, EventCallback
from .audit import AuditLog
from .hub import MCPHub, load_server_params
from .llm import DEFAULT_GEMINI_MODEL, DEFAULT_NVIDIA_MODEL, make_llm
from .memory import MemoryStore
from .models import ToolInfo
from .policy import Policy
from .tracing import Metrics, load_pricing


@dataclass
class Runtime:
    agent: Agent
    hub: MCPHub
    policy: Policy
    metrics: Metrics
    audit: AuditLog
    provider: str
    model: str

    async def close(self) -> None:
        await self.hub.close()


async def deny_all(info: ToolInfo, args: dict) -> bool:
    return False


async def approve_all(info: ToolInfo, args: dict) -> bool:
    return True


def resolve_provider(requested: str) -> str:
    """Choose the LLM provider, preferring NVIDIA when credentials exist."""

    if requested == "auto":
        if config.have_nvidia_credentials():
            return "nvidia"

        if config.have_gemini_credentials():
            return "gemini"

        return "mock"

    if requested not in {"nvidia", "gemini", "mock"}:
        raise ValueError(
            f"Unknown provider '{requested}'. Use 'auto', 'nvidia', 'gemini', or 'mock'."
        )

    return requested


async def build_runtime(
    *,
    provider: str = "auto",
    model: str | None = None,
    profile: str = "standard",
    approver: Approver = deny_all,
    on_event: EventCallback | None = None,
    reflect: bool = False,
    servers_file: Path | None = None,
    policy_file: Path | None = None,
    only_servers: set[str] | None = None,
) -> Runtime:
    """Build and return the complete assistant runtime."""

    provider = resolve_provider(provider)

    if provider == "mock":
        model_name = "mock"
    elif provider == "nvidia":
     model_name = (
        model
        or os.environ.get("NVIDIA_MODEL")
        or DEFAULT_NVIDIA_MODEL
    )
    elif provider == "gemini":
        model_name = model or DEFAULT_GEMINI_MODEL
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    llm = make_llm(provider, model_name)

    policy = Policy.load(
        policy_file or config.ROOT / "config" / "policy.yaml",
        profile,
    )

    hub = MCPHub()

    await hub.start(
        load_server_params(
            servers_file or config.ROOT / "config" / "mcp_servers.json",
            only_servers,
        )
    )

    logs = config.logs_dir()

    audit = AuditLog(logs / "audit.jsonl")

    metrics = Metrics(
        model_name,
        load_pricing(config.ROOT / "config" / "pricing.yaml"),
        logs / "traces.jsonl",
    )

    memory = MemoryStore(config.data_dir() / "memory.json")

    agent = Agent(
        hub,
        llm,
        policy,
        audit,
        metrics,
        memory,
        approver,
        on_event,
        reflect,
    )

    return Runtime(
        agent,
        hub,
        policy,
        metrics,
        audit,
        provider,
        model_name,
    )
