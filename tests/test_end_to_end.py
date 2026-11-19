"""End-to-end: real MCP servers over stdio + the agent loop, driven by the offline mock model."""
import asyncio
import json

from mcp_assistant import config
from mcp_assistant.runtime import approve_all, build_runtime, deny_all

EXPECTED_TOOLS = {
    "files__read_file", "files__write_file", "db__query", "db__execute_write", "repo__git_log", "repo__search_code",
    "cloud__cloud_status", "cloud__bq_query", "apps__slack_post_message", "apps__gmail_send", "apps__notion_search",
    "web__web_search", "web__fetch_url", "api__api_get", "api__api_call", "utility__calculate",
    "knowledge__search_knowledge", "memory__remember",
}


def run(coro):
    return asyncio.run(coro)


def test_every_server_starts_and_exposes_tools(env):
    async def go():
        rt = await build_runtime(provider="mock")
        try:
            status = {n: (ok, err) for n, ok, _, err in rt.hub.status()}
            assert all(ok for ok, _ in status.values()), status
            assert EXPECTED_TOOLS <= set(rt.hub.tools), EXPECTED_TOOLS - set(rt.hub.tools)
            # annotations flow through MCP into the policy
            assert rt.hub.tools["db__query"].read_only and not rt.hub.tools["files__write_file"].read_only
        finally:
            await rt.close()
    run(go())


def test_agent_reads_files_and_database(env):
    async def go():
        rt = await build_runtime(provider="mock", only_servers={"files", "db", "utility"})
        try:
            r = await rt.agent.run_turn("List the files in the workspace.")
            assert [c["name"] for c in r.tool_calls] == ["files__list_directory"] and "docs" in r.answer
            r = await rt.agent.run_turn("Show me the overdue invoices")
            assert "INV-2026" in r.answer and r.tool_calls[0]["status"] == "ok"
            r = await rt.agent.run_turn("Calculate 450000 * 0.18")
            assert "81000" in r.answer
            assert r.metrics.llm_calls == 2 and r.metrics.tool_calls == 1
        finally:
            await rt.close()
    run(go())


def test_sql_guard_and_sandbox_through_mcp(env):
    async def go():
        rt = await build_runtime(provider="mock", only_servers={"files", "db"})
        try:
            text, err = await rt.hub.call("db__query", {"sql": "DROP TABLE customers"})
            assert err and "Only SELECT" in text
            text, err = await rt.hub.call("db__query", {"sql": "SELECT COUNT(*) AS n FROM customers"})
            assert not err and "12" in text  # table still intact
            text, err = await rt.hub.call("db__execute_write", {"sql": "DELETE FROM customers"})
            assert err
            text, err = await rt.hub.call("db__execute_write", {"sql": "UPDATE customers SET city = 'X'"})
            assert err and "WHERE" in text
            text, err = await rt.hub.call("files__read_file", {"path": "../pyproject.toml"})
            assert err and "outside" in text
            text, err = await rt.hub.call("files__write_file", {"path": "evil.py", "content": "print(1)"})
            assert err and "not allowed" in text
        finally:
            await rt.close()
    run(go())


def test_readonly_profile_hides_write_tools(env):
    async def go():
        rt = await build_runtime(provider="mock", profile="readonly", only_servers={"apps", "files"})
        try:
            visible = {t.qualified for t in rt.agent.visible_tools()}
            assert "files__read_file" in visible
            assert "apps__slack_post_message" not in visible and "files__write_file" not in visible
            r = await rt.agent.run_turn("Post 'hi' to slack")
            assert not r.tool_calls and "not available" in r.answer
        finally:
            await rt.close()
    run(go())


def test_write_needs_approval_and_is_audited(env):
    async def go():
        rt = await build_runtime(provider="mock", only_servers={"apps"}, approver=deny_all)
        try:
            r = await rt.agent.run_turn("Post 'hello team' to the slack channel")
            assert r.tool_calls[0]["status"] == "declined"
        finally:
            await rt.close()
        rt = await build_runtime(provider="mock", only_servers={"apps"}, approver=approve_all)
        try:
            r = await rt.agent.run_turn("Post 'hello team' to the slack channel")
            assert r.tool_calls[0]["status"] == "ok" and "DRY RUN" in r.answer  # safe-by-default dry run
        finally:
            await rt.close()
        lines = [json.loads(x) for x in (config.logs_dir() / "audit.jsonl").read_text().splitlines()]
        statuses = [l["status"] for l in lines if l.get("tool") == "apps__slack_post_message"]
        assert statuses == ["declined", "ok"]
    run(go())


def test_prompt_injection_is_flagged(env):
    async def go():
        rt = await build_runtime(provider="mock", only_servers={"files"})
        try:
            r = await rt.agent.run_turn("Read notes/vendor_email_dump.txt")
            assert r.tool_calls[0]["injection_flags"]
            assert "SECURITY NOTICE" in rt.agent.history[2].tool_results[0].content
        finally:
            await rt.close()
    run(go())


def test_rag_and_memory(env):
    async def go():
        rt = await build_runtime(provider="mock", only_servers={"knowledge", "memory"})
        try:
            r = await rt.agent.run_turn("What is the refund policy approval limit?")
            assert "refund_policy.md" in r.answer
            await rt.agent.run_turn("Remember that I prefer INR lakhs")
            assert any("INR lakhs" in m["fact"] for m in rt.agent.memory.__class__(config.data_dir() / "memory.json").items)
        finally:
            await rt.close()
    run(go())
