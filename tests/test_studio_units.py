"""Pure-logic tests: text parsers for the file/git tools and NVIDIA SSE streaming (simulated server, no network)."""
import asyncio
import json

import httpx

from mcp_assistant.llm.nvidia import NvidiaLLM
from mcp_assistant.models import Message
from mcp_assistant.studio.parsers import parse_directory, parse_git_log, parse_git_status, parse_search_hits, parse_tree


def test_parse_directory_and_search_hits():
    out = parse_directory("[dir]  docs/\n[file] docs/a.md  (1,234 bytes)\n[file] x.txt  (5 bytes)")
    assert out[0] == {"type": "dir", "path": "docs", "name": "docs", "size": None}
    assert out[1]["size"] == 1234 and out[1]["name"] == "a.md"
    hits = parse_search_hits("docs/a.md:3: refund policy\nnotes/b.md (file name match)")
    assert hits[0] == {"path": "docs/a.md", "line": 3, "text": "refund policy"} and hits[1]["line"] is None


def test_parse_tree_nests_by_indent():
    tree = parse_tree("src/\n  pkg/\n    a.py\n  b.py\nREADME.md")
    assert [n["name"] for n in tree] == ["src", "README.md"]
    assert tree[0]["children"][0]["children"][0]["path"] == "src/pkg/a.py" and tree[0]["children"][1]["type"] == "file"


def test_parse_git_status_branches_and_files():
    s = parse_git_status("## main...origin/main [ahead 2, behind 1]\nM  staged.py\n M modified.py\nMM both.py\n?? new.txt\n D gone.py")
    assert (s["branch"], s["upstream"], s["ahead"], s["behind"]) == ("main", "origin/main", 2, 1)
    assert [e["path"] for e in s["staged"]] == ["staged.py", "both.py"]
    assert [e["path"] for e in s["modified"]] == ["modified.py", "both.py", "gone.py"]
    assert [e["path"] for e in s["untracked"]] == ["new.txt"] and not s["clean"]
    assert parse_git_status("## No commits yet on main")["branch"] == "main"
    assert parse_git_status("## dev")["clean"]


def test_parse_git_log():
    c = parse_git_log("abc1234 2026-11-01 Asha Rao: Fix: invoice rounding\nbad line")
    assert c == [{"hash": "abc1234", "date": "2026-11-01", "author": "Asha Rao", "subject": "Fix: invoice rounding"}]


def _sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _llm(monkeypatch, handler) -> NvidiaLLM:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    llm = NvidiaLLM("nvidia/test-model")
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=llm.client.headers)
    return llm


def test_nvidia_streams_tokens_and_reassembles_tool_calls(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "Let me "}}]},
            {"choices": [{"delta": {"content": "check."}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "db__query", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "db__query", "arguments": "{\"sql\": \"SELECT 1\""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}}]},
            {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 33}},
        ), headers={"content-type": "text/event-stream"})

    async def go():
        llm = _llm(monkeypatch, handler)
        pieces: list[str] = []
        llm.on_token = pieces.append
        resp = await llm.generate("sys", [Message("user", text="hi")], [])
        await llm.client.aclose()
        return pieces, resp

    pieces, resp = asyncio.run(go())
    assert seen["body"]["stream"] is True and seen["body"]["stream_options"] == {"include_usage": True}
    assert pieces == ["Let me ", "check."] and resp.text == "Let me check."
    assert [(c.name, c.args) for c in resp.tool_calls] == [("db__query", {"sql": "SELECT 1"})]
    assert (resp.usage.input_tokens, resp.usage.output_tokens) == (120, 33)


def test_nvidia_without_callback_does_not_stream(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "stream" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    async def go():
        llm = _llm(monkeypatch, handler)
        r = await llm.generate("sys", [Message("user", text="hi")], [])
        await llm.client.aclose()
        return r

    assert asyncio.run(go()).text == "hello"


def test_nvidia_stream_error_retries_when_nothing_shown_yet(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="overloaded")

    async def go():
        llm = _llm(monkeypatch, handler)
        llm.on_token = lambda _t: None
        try:
            await llm.generate("sys", [Message("user", text="hi")], [])
        finally:
            await llm.client.aclose()

    import pytest

    real_sleep = asyncio.sleep

    async def fast_sleep(*_a, **_k):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    with pytest.raises(RuntimeError, match="NVIDIA API error \\(503\\)"):
        asyncio.run(go())
    assert calls["n"] == 4  # nothing had been shown to the user yet, so the normal 4-attempt retry applies
