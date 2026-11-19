"""Offline checks of the Gemini adapter: schema conversion, history replay and response parsing."""
import asyncio
from types import SimpleNamespace

from google.genai import types

from mcp_assistant.llm.gemini import GeminiLLM
from mcp_assistant.models import Message, ToolCall, ToolInfo, ToolResult
from mcp_assistant.runtime import build_runtime


class _FakeModels:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self.response


def _llm_with(response):
    llm = GeminiLLM.__new__(GeminiLLM)  # skip genai.Client() so no API key is needed
    llm.name = llm.model = "gemini-test"
    llm.temperature = 0.2
    fake = _FakeModels(response)
    llm.client = SimpleNamespace(aio=SimpleNamespace(models=fake))
    return llm, fake


def test_parses_function_calls_text_and_usage():
    content = types.Content(role="model", parts=[
        types.Part(text="Let me check."),
        types.Part(function_call=types.FunctionCall(id="c1", name="db__query", args={"sql": "SELECT 1"})),
    ])
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=content)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=120, candidates_token_count=15, thoughts_token_count=5),
    )
    llm, fake = _llm_with(resp)
    out = asyncio.run(llm.generate("sys", [Message("user", text="hi")], []))
    assert out.text == "Let me check."
    assert out.tool_calls == [ToolCall(id="c1", name="db__query", args={"sql": "SELECT 1"})]
    assert (out.usage.input_tokens, out.usage.output_tokens) == (120, 20)
    assert out.raw is content  # replayed verbatim next turn (keeps thought signatures)
    assert fake.calls[0]["config"].automatic_function_calling.disable is True


def test_history_conversion_roundtrip():
    history = [
        Message("user", text="count customers"),
        Message("model", tool_calls=[ToolCall("c1", "db__query", {"sql": "SELECT 1"})]),
        Message("tool", tool_results=[ToolResult("c1", "db__query", "n\n12"), ToolResult("c2", "x__y", "boom", is_error=True)]),
    ]
    contents = GeminiLLM._to_contents(history)
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].function_call.name == "db__query"
    assert contents[2].parts[0].function_response.response == {"result": "n\n12"}
    assert contents[2].parts[1].function_response.response == {"error": "boom"}


def test_empty_response_is_handled():
    llm, _ = _llm_with(types.GenerateContentResponse(candidates=[]))
    out = asyncio.run(llm.generate("sys", [Message("user", text="hi")], []))
    assert "no content" in out.text and not out.tool_calls


def test_every_real_tool_schema_is_accepted_by_the_sdk(env):
    async def go():
        rt = await build_runtime(provider="mock")
        try:
            llm, fake = _llm_with(types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text="ok")]))]))
            await llm.generate("sys", [Message("user", text="hi")], list(rt.hub.tools.values()))
            decls = fake.calls[0]["config"].tools[0].function_declarations
            assert len(decls) == len(rt.hub.tools) > 40
            assert all(len(d.name) <= 64 for d in decls)  # Gemini's function-name limit
        finally:
            await rt.close()

    asyncio.run(go())
