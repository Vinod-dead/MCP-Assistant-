"""Gemini provider (Google AI Studio key or Vertex AI) using native function calling.

Credentials: set GEMINI_API_KEY (or GOOGLE_API_KEY). For Vertex AI instead set
GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION and sign in with
`gcloud auth application-default login`.
"""
from __future__ import annotations

import asyncio
import copy
from typing import Any

from google import genai
from google.genai import errors, types

from ..models import LLMResponse, Message, ToolCall, ToolInfo, Usage


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(schema)
    schema.pop("title", None)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


class GeminiLLM:
    def __init__(self, model: str, temperature: float = 0.2) -> None:
        self.name = model
        self.model = model
        self.temperature = temperature
        self.client = genai.Client()  # picks up GEMINI_API_KEY / GOOGLE_API_KEY / Vertex env vars

    # ------------------------------------------------------------------ conversion
    @staticmethod
    def _to_contents(messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
            elif m.role == "model":
                if m.raw is not None:  # replay exactly what the model produced (keeps thought signatures)
                    contents.append(m.raw)
                else:
                    parts = [types.Part(text=m.text)] if m.text else []
                    parts += [types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.args)) for c in m.tool_calls]
                    contents.append(types.Content(role="model", parts=parts))
            else:  # tool results
                parts = [
                    types.Part(function_response=types.FunctionResponse(
                        id=r.call_id, name=r.name, response={"error" if r.is_error else "result": r.content}))
                    for r in m.tool_results
                ]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    # ------------------------------------------------------------------- generation
    async def generate(self, system: str, messages: list[Message], tools: list[ToolInfo]) -> LLMResponse:
        decls = [
            types.FunctionDeclaration(
                name=t.qualified,
                description=(t.description or t.name)[:1000],
                parameters_json_schema=_clean_schema(t.input_schema),
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = self._to_contents(messages)

        resp = None
        for attempt in range(4):
            try:
                resp = await self.client.aio.models.generate_content(model=self.model, contents=contents, config=config)
                break
            except errors.APIError as exc:
                retryable = getattr(exc, "code", 0) in (429, 500, 503, 504)
                if not retryable or attempt == 3:
                    raise
                await asyncio.sleep(2**attempt)
        assert resp is not None

        usage = Usage()
        if resp.usage_metadata:
            usage.input_tokens = resp.usage_metadata.prompt_token_count or 0
            usage.output_tokens = (resp.usage_metadata.candidates_token_count or 0) + (resp.usage_metadata.thoughts_token_count or 0)

        if not resp.candidates or not resp.candidates[0].content:
            reason = resp.candidates[0].finish_reason if resp.candidates else "no candidates"
            return LLMResponse(text=f"(The model returned no content: {reason})", usage=usage)

        content = resp.candidates[0].content
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for i, part in enumerate(content.parts or []):
            if part.function_call:
                fc = part.function_call
                calls.append(ToolCall(id=fc.id or f"call_{i}", name=fc.name, args=dict(fc.args or {})))
            elif part.text and not part.thought:
                text_parts.append(part.text)
        return LLMResponse(text="".join(text_parts).strip(), tool_calls=calls, usage=usage, raw=content)


def list_models() -> list[str]:
    client = genai.Client()
    return sorted(
        m.name.removeprefix("models/")
        for m in client.models.list()
        if "generateContent" in (m.supported_actions or [])
    )
