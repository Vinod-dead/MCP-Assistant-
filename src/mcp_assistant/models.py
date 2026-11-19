"""Small shared data types (provider-neutral)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False
    destructive: bool = True  # MCP spec default for tools that are not read-only
    open_world: bool = True  # MCP spec default: may touch the outside world

    @property
    def qualified(self) -> str:
        return f"{self.server}__{self.name}"


@dataclass
class ToolCall:
    id: str
    name: str  # qualified name, e.g. "db__query"
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw: Any = None  # provider-specific payload kept so history can be replayed faithfully


@dataclass
class Message:
    role: Literal["user", "model", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None
