
"""NVIDIA NIM provider using the OpenAI-compatible Chat Completions API."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from openai import AsyncOpenAI

from ..models import LLMResponse, Message, ToolCall, ToolInfo, Usage


class NvidiaLLM:
    def __init__(self, model: str, temperature: float = 0.2) -> None:
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is missing. Add it to your .env file.")

        self.name = model
        self.model = model
        self.temperature = temperature

        self.client = AsyncOpenAI(
            base_url=os.environ.get(
                "NVIDIA_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ),
            api_key=api_key,
            timeout=90.0,
        )

    @staticmethod
    def _messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = [
            {"role": "system", "content": system}
        ]

        for message in messages:
            if message.role == "user":
                result.append({
                    "role": "user",
                    "content": message.text,
                })

            elif message.role == "model":
                assistant: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.text or None,
                }

                if message.tool_calls:
                    assistant["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.args),
                            },
                        }
                        for call in message.tool_calls
                    ]

                result.append(assistant)

            elif message.role == "tool":
                for tool_result in message.tool_results:
                    content = tool_result.content
                    if tool_result.is_error:
                        content = f"Tool error: {content}"

                    result.append({
                        "role": "tool",
                        "tool_call_id": tool_result.call_id,
                        "content": content,
                    })

        return result

    async def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolInfo],
    ) -> LLMResponse:

        tool_definitions = [
            {
                "type": "function",
                "function": {
                    "name": tool.qualified,
                    "description": (tool.description or tool.name)[:1000],
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

        request: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "temperature": self.temperature,
        }

        if tool_definitions:
            request["tools"] = tool_definitions
            request["tool_choice"] = "auto"

        response = None

        for attempt in range(4):
            try:
                response = await self.client.chat.completions.create(
                    **request
                )
                break
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise

                await asyncio.sleep(2 ** attempt)

        if response is None:
            raise RuntimeError("NVIDIA API returned no response.")

        usage = Usage()

        if response.usage:
            usage.input_tokens = response.usage.prompt_tokens or 0
            usage.output_tokens = response.usage.completion_tokens or 0

        choice = response.choices[0]
        assistant_message = choice.message

        calls: list[ToolCall] = []

        for index, call in enumerate(assistant_message.tool_calls or []):
            try:
                arguments = json.loads(call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid arguments returned for tool {call.function.name}: {exc}"
                ) from exc

            calls.append(
                ToolCall(
                    id=call.id or f"call_{index}",
                    name=call.function.name,
                    args=arguments,
                )
            )

        return LLMResponse(
            text=assistant_message.content or "",
            tool_calls=calls,
            usage=usage,
            raw=None,
        )

    async def close(self) -> None:
        await self.client.close()
