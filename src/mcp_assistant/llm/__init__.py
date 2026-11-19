
from __future__ import annotations

from .base import LLM

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def make_llm(provider: str, model: str | None = None) -> LLM:
    if provider == "mock":
        from .mock import MockLLM
        return MockLLM()

    if provider == "gemini":
        from .gemini import GeminiLLM
        return GeminiLLM(model or DEFAULT_GEMINI_MODEL)

    if provider == "nvidia":
        from .nvidia import NvidiaLLM
        return NvidiaLLM(model or DEFAULT_NVIDIA_MODEL)

    raise ValueError(
        f"Unknown provider '{provider}' (use 'nvidia', 'gemini', or 'mock')."
    )
