"""LLM provider interface."""
from __future__ import annotations

from typing import Protocol

from ..models import LLMResponse, Message, ToolInfo


class LLM(Protocol):
    name: str

    async def generate(self, system: str, messages: list[Message], tools: list[ToolInfo]) -> LLMResponse: ...
