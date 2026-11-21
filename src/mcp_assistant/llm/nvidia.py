
"""NVIDIA NIM provider using HTTPX and the OpenAI-compatible Chat Completions API."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from ..models import LLMResponse, Message, ToolCall, ToolInfo, Usage


class NvidiaLLM:
    def __init__(self, model: str, temperature: float = 0.2) -> None:
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is missing. Add it to your .env file.")

        self.name = model
        self.model = model
        self.temperature = temperature

        base_url = os.environ.get(
            "NVIDIA_BASE_URL",
            "https://integrate.api.nvidia.com/v1",
        ).rstrip("/")

        self.url = f"{base_url}/chat/completions"

        self.client = httpx.AsyncClient(
            timeout=90.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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

        response_data = None

        for attempt in range(4):
            try:
                response = await self.client.post(
                    self.url,
                    json=request,
                )
                response.raise_for_status()
                response_data = response.json()
                break

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code

                if status not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError(
                        f"NVIDIA API error ({status}): {exc.response.text[:2000]}"
                    ) from exc

                await asyncio.sleep(2 ** attempt)

            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 3:
                    raise

                await asyncio.sleep(2 ** attempt)

        if response_data is None:
            raise RuntimeError("NVIDIA API returned no response.")

        usage = Usage()
        usage_data = response_data.get("usage") or {}

        usage.input_tokens = usage_data.get("prompt_tokens") or 0
        usage.output_tokens = usage_data.get("completion_tokens") or 0

        choices = response_data.get("choices") or []
        if not choices:
            raise RuntimeError(
                f"NVIDIA API returned no choices: {response_data}"
            )

        assistant_message = choices[0].get("message") or {}

        calls: list[ToolCall] = []

        for index, call in enumerate(
            assistant_message.get("tool_calls") or []
        ):
            function = call.get("function") or {}
            function_name = function.get("name", "unknown")

            try:
                arguments = json.loads(function.get("arguments") or "{}")

                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")

            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid arguments returned for tool "
                    f"{function_name}: {exc}"
                ) from exc

            calls.append(
                ToolCall(
                    id=call.get("id") or f"call_{index}",
                    name=function_name,
                    args=arguments,
                )
            )

        return LLMResponse(
            text=assistant_message.get("content") or "",
            tool_calls=calls,
            usage=usage,
            raw=None,
        )

    async def close(self) -> None:
        await self.client.aclose()
