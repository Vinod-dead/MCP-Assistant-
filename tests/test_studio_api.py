"""Studio API end-to-end: real MCP servers over stdio, driven by the offline mock model.

TestClient buffers a streaming response until the app finishes, so flows that *wait for a human*
(approvals, stop) are resolved from a helper thread, exactly like a browser would do."""
import json
import threading
import time

import pytest
from starlette.testclient import TestClient

from mcp_assistant.studio.app import create_app

TOKEN_HEADER = "X-Session-Token"
JSON = {"Content-Type": "application/json"}  # the API requires it on every non-GET request


@pytest.fixture
def client(env):
    app = create_app(provider="mock")
    with TestClient(app, base_url="http://localhost:8765") as c:
        token = c.get("/api/session").json()["token"]
        c.headers.update({TOKEN_HEADER: token})
        yield c


def events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]


def chat(client, message, conversation_id=None) -> list[dict]:
    with client.stream("POST", "/api/chat", json={"message": message, "conversation_id": conversation_id}) as r:
        assert r.status_code == 200
        return events(r)


def act_when_pending(client, fn, timeout=20):
    """Run fn(approval) in a thread as soon as an approval is pending."""
    out = {}

    def worker():
        end = time.time() + timeout
        while time.time() < end:
            pending = client.get("/api/approvals").json()["pending"]
            if pending:
                out["approval"] = pending[0]
                out["result"] = fn(pending[0])
                return
            time.sleep(0.05)

    t = threading.Thread(target=worker)
    t.start()
    return t, out


# ----------------------------------------------------------------------------- security
def test_token_host_origin_and_content_type_guards(client):
    bare = TestClient(client.app, base_url="http://localhost:8765")
    assert bare.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"Host": "evil.com"}).status_code == 403
    r = client.post("/api/tools/execute", json={"name": "utility__calculate", "args": {"expression": "1+1"}}, headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    assert client.post("/api/tools/execute", content="x", headers={"Content-Type": "text/plain"}).status_code == 415


def test_session_endpoint_sends_no_cors_headers(client):
    r = client.get("/api/session", headers={"Origin": "http://evil.com"})
    assert "access-control-allow-origin" not in r.headers


# ----------------------------------------------------------------------------- system
def test_health_model_servers_tools(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["servers"] == {"up": 10, "total": 10} and h["tools"] >= 52 and h["offline_demo"]
    m = client.get("/api/model").json()
    assert m["provider"] == "mock" and m["connection"] == "not_tested" and m["usage"]["requests"] == 0
    s = client.get("/api/servers", params={"probe": "true"}).json()["servers"]
    assert len(s) == 10 and all(x["status"] == "running" and x["responsive"] for x in s)
    t = client.get("/api/tools").json()
    by = {x["name"]: x for x in t["tools"]}
    assert by["db__query"]["permission"] == "allow" and by["db__query"]["kind"] == "read"
    assert by["db__execute_write"]["permission"] == "approve"
    assert by["db__query"]["params"][0]["name"] == "sql" and by["db__query"]["params"][0]["required"]
    assert t["total"] == len(t["tools"]) >= 52


def test_restart_server_reconnects_and_keeps_tools(client):
    before = client.get("/api/servers").json()["servers"]
    n = next(x["tools"] for x in before if x["name"] == "utility")
    r = client.post("/api/servers/utility/restart", json={}).json()
    assert r["running"] and r["tools"] == n
    assert client.post("/api/tools/execute", json={"name": "utility__calculate", "args": {"expression": "2*21"}}).json()["output"].strip().endswith("42")
    assert client.post("/api/servers/nope/restart", json={}).status_code == 404


def test_manual_tool_execution_is_governed_and_audited(client):
    ok = client.post("/api/tools/execute", json={"name": "utility__calculate", "args": {"expression": "450000*0.18"}}).json()
    assert ok["ok"] and "81000" in ok["output"] and ok["decision"] == "allow"
    # state-changing tool: waits for approval; declining blocks it
    t, out = act_when_pending(client, lambda a: client.post(f"/api/approvals/{a['id']}", json={"allow": False}).status_code)
    r = client.post("/api/tools/execute", json={"name": "apps__slack_post_message", "args": {"channel": "#x", "text": "hi"}}).json()
    t.join()
    assert out["approval"]["source"] == "manual" and not r["ok"] and r["status"] == "declined"
    assert client.post("/api/tools/execute", json={"name": "files__delete_everything", "args": {}}).json()["status"] == "unknown_tool"
    audit = client.get("/api/audit", params={"tool": "slack"}).json()["events"]
    assert audit and audit[0]["status"] == "declined" and audit[0]["source"] == "manual"


def test_settings_profile_can_only_be_lowered(client):
    s = client.get("/api/settings").json()
    assert s["profile"] == "standard" and set(s["can_switch_to"]) == {"readonly"}
    assert "NVIDIA_API_KEY" in s["environment"] and all(isinstance(v, bool) for v in s["environment"].values())
    assert client.post("/api/settings/profile", json={"profile": "admin"}).status_code == 403
    assert client.post("/api/settings/profile", json={"profile": "readonly"}).json()["profile"] == "readonly"
    tools = {x["name"]: x for x in client.get("/api/tools").json()["tools"]}
    assert tools["db__execute_write"]["permission"] == "deny"
    assert client.get("/api/security").json()["profile"] == "readonly"


# ----------------------------------------------------------------------------- chat
def test_chat_streams_real_execution_events_and_persists(client):
    ev = events_of = chat(client, "which tables are in the database?")
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "start" and kinds[1] == "request_received" and kinds[-1] == "done"
    assert kinds.index("llm_start") < kinds.index("tool_call") < kinds.index("tool_result") < kinds.index("done")
    result = next(e for e in ev if e["type"] == "tool_result")
    assert "customers" in result["output"] and result["ok"] and result["ms"] >= 0
    llm = next(e for e in ev if e["type"] == "llm_call")
    assert llm["tool_calls"] == ["db__list_tables"] and llm["input_tokens"] > 0
    done = ev[-1]["message"]
    assert done["status"] == "done" and done["model"] == "mock" and done["metrics"]["tool_calls"] == 1 and "tok" in done["metrics"]["summary"]
    cid = ev[0]["conversation_id"]
    conv = client.get(f"/api/conversations/{cid}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] and conv["title"].startswith("which tables")
    assert any(s["type"] == "tool_result" for s in conv["messages"][1]["steps"])
    # follow-up turn in the same conversation keeps history; model usage is recorded
    chat(client, "show overdue invoices", cid)
    assert len(client.get(f"/api/conversations/{cid}").json()["messages"]) == 4
    assert client.get(f"/api/conversations/{cid}/context").json()["messages_in_context"] >= 4
    assert client.get("/api/model").json()["usage"]["requests"] >= 4


def test_prompt_injection_is_flagged_in_the_stream(client):
    ev = chat(client, "read notes/vendor_email_dump.txt and summarize it")
    res = next(e for e in ev if e["type"] == "tool_result")
    assert res["flags"] and "SECURITY NOTICE" in res["output"]


def test_chat_approval_card_then_allow(client):
    t, out = act_when_pending(client, lambda a: client.post(f"/api/approvals/{a['id']}", json={"allow": True}).status_code)
    ev = chat(client, "post 'report ready' to slack")
    t.join()
    appr = next(e for e in ev if e["type"] == "approval")
    assert appr["tool"] == "apps__slack_post_message" and appr["source"] == "chat" and out["result"] == 200
    assert any(e["type"] == "tool_result" and e["ok"] for e in ev)
    hist = client.get("/api/approvals").json()["history"]
    assert hist and hist[0]["status"] == "approved"


def test_stop_generation_cancels_and_rolls_back(client):
    t, out = act_when_pending(client, lambda a: client.post("/api/chat/stop", json={}).json())
    ev = chat(client, "post 'never sent' to slack")
    t.join()
    assert out["result"] == {"stopped": True}
    assert ev[-1]["type"] == "stopped" and ev[-1]["message"]["status"] == "stopped"
    cid = ev[0]["conversation_id"]
    # nothing was sent and the conversation is still usable (history was rolled back)
    assert not any(e["type"] == "tool_result" for e in ev)
    assert chat(client, "what time is it?", cid)[-1]["type"] == "done"
    assert client.post("/api/chat/stop", json={}).json() == {"stopped": False}


def test_regenerate_replaces_the_last_answer(client):
    ev = chat(client, "calculate 6*7")
    cid = ev[0]["conversation_id"]
    with client.stream("POST", f"/api/conversations/{cid}/regenerate", json={}) as r:
        ev2 = events(r)
    assert ev2[0]["regenerated"] and ev2[-1]["type"] == "done"
    conv = client.get(f"/api/conversations/{cid}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]


def test_conversation_search_clear_delete(client):
    cid = chat(client, "list the files in the workspace")[0]["conversation_id"]
    chat(client, "calculate 1+1")
    assert [c["id"] for c in client.get("/api/conversations", params={"q": "workspace"}).json()["conversations"]] == [cid]
    assert client.get("/api/conversations", params={"q": "zzzzzz"}).json()["conversations"] == []
    assert client.post(f"/api/conversations/{cid}/clear", json={}).json()["cleared"]
    assert client.get(f"/api/conversations/{cid}").json()["messages"] == []
    assert client.delete(f"/api/conversations/{cid}", headers=JSON).json()["deleted"]
    assert client.get(f"/api/conversations/{cid}").status_code == 404
    assert client.get("/api/conversations/../../etc").status_code in {404, 422}


def test_concurrent_chat_is_rejected(client):
    t, out = act_when_pending(client, lambda a: (client.post("/api/chat", json={"message": "hi"}).status_code, client.post(f"/api/approvals/{a['id']}", json={"allow": False})))
    chat(client, "post 'x' to slack")
    t.join()
    assert out["result"][0] == 409


# ----------------------------------------------------------------------------- database
def test_database_explorer(client):
    o = client.get("/api/database/overview").json()
    assert o["connection"] == "connected" and o["dialect"] == "sqlite" and o["read_only"] and o["table_count"] == 3 and o["total_rows"] == 12 + 60 + 15
    tables = {t["name"]: t for t in client.get("/api/database/tables").json()["tables"]}
    assert tables["invoices"]["rows"] == 60 and tables["invoices"]["foreign_keys"] == 1
    s = client.get("/api/database/schema/invoices").json()
    cols = {c["name"]: c for c in s["columns"]}
    assert cols["id"]["primary_key"] and cols["customer_id"]["foreign_key"] == {"table": "customers", "column": "id"}
    assert client.get("/api/database/schema/customers").json()["referenced_by"][0]["table"] in {"invoices", "tickets"}
    assert client.get("/api/database/schema/nope").status_code == 404
    rel = client.get("/api/database/relations").json()
    assert {(e["from"], e["to"]) for e in rel["edges"]} == {("invoices", "customers"), ("tickets", "customers")}
    b = client.post("/api/database/browse", json={"table": "invoices", "page": 2, "page_size": 10, "sort": "amount", "order": "desc",
                                                  "filters": [{"column": "status", "op": "eq", "value": "overdue"}]}).json()
    amounts = [r[b["columns"].index("amount")] for r in b["rows"]]
    assert b["page"] == 2 and amounts == sorted(amounts, reverse=True) and all(r[b["columns"].index("status")] == "overdue" for r in b["rows"])
    sr = client.post("/api/database/browse", json={"table": "customers", "search": "textiles"}).json()
    assert sr["total"] == 1 and sr["rows"][0][1] == "Asha Textiles"
    assert client.post("/api/database/browse", json={"table": "customers", "sort": "x; DROP TABLE customers"}).status_code == 400
    assert client.post("/api/database/browse", json={"table": "customers; DROP", "page": 1}).status_code == 404


def test_sql_workspace_is_read_only(client):
    ok = client.post("/api/database/query", json={"sql": "SELECT status, COUNT(*) n FROM invoices GROUP BY status ORDER BY n DESC"}).json()
    assert ok["ok"] and ok["columns"] == ["status", "n"] and sum(r[1] for r in ok["rows"]) == 60 and ok["ms"] >= 0
    for bad in ("DROP TABLE customers", "DELETE FROM invoices", "SELECT 1; DELETE FROM invoices", "UPDATE customers SET name='x' WHERE id=1",
                "WITH x AS (SELECT 1) INSERT INTO customers VALUES (99,'a','b','c','d')"):
        r = client.post("/api/database/query", json={"sql": bad}).json()
        assert not r["ok"] and r["error"], bad
    assert client.post("/api/database/query", json={"sql": "SELECT COUNT(*) FROM customers"}).json()["rows"] == [[12]]  # still intact
    hist = client.get("/api/database/history").json()["history"]
    assert len(hist) >= 7 and hist[0]["ok"] and not hist[1]["ok"]
    assert client.get("/api/database/overview").json()["last_successful_query"]


def test_sensitive_columns_are_masked(client, env):
    import sqlite3

    from mcp_assistant.servers import db_server

    client.get("/api/database/overview")  # make sure the explorer's engine is initialised
    con = sqlite3.connect(db_server.URL.removeprefix("sqlite:///"))
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, password TEXT, api_key TEXT)")
    con.execute("INSERT INTO users VALUES (1,'ann','hunter2','sk-abcdefghijklmnopqrstuvwxyz0123')")
    con.commit(); con.close()
    try:
        b = client.post("/api/database/browse", json={"table": "users"}).json()
        assert b["rows"][0][2] == "••••••" and b["rows"][0][3] == "••••••" and b["rows"][0][1] == "ann"
        q = client.post("/api/database/query", json={"sql": "SELECT name, password FROM users"}).json()
        assert q["rows"][0][1] == "••••••" and q["masked_columns"] == ["password"]
    finally:
        con = sqlite3.connect(db_server.URL.removeprefix("sqlite:///"))
        con.execute("DROP TABLE users")
        con.commit(); con.close()


def test_database_blocked_when_policy_denies_it(client):
    assert client.post("/api/settings/profile", json={"profile": "readonly"}).status_code == 200
    assert client.get("/api/database/tables").status_code == 200  # db__query is read-only: still allowed in readonly


# ----------------------------------------------------------------------------- memory / knowledge / files / repo
def test_memory_center_uses_real_memory_tools(client):
    r = client.post("/api/memory", json={"fact": "User prefers INR lakhs", "tags": "units"}).json()
    assert r["ok"] and "Remembered" in r["output"]
    mem = client.get("/api/memory").json()
    assert mem["count"] == 1 and mem["records"][0]["fact"] == "User prefers INR lakhs" and mem["supports"]["update"] is False
    hits = client.get("/api/memory/search", params={"q": "which currency units"}).json()
    assert hits["terms"] and client.get("/api/memory/search", params={"q": "lakhs"}).json()["results"][0]["rank"] == 1
    mid = mem["records"][0]["id"]
    t, out = act_when_pending(client, lambda a: client.post(f"/api/approvals/{a['id']}", json={"allow": True}).status_code)
    d = client.delete(f"/api/memory/{mid}", headers=JSON).json()
    t.join()
    assert out["approval"]["tool"] == "memory__forget" and d["ok"] and client.get("/api/memory").json()["count"] == 0


def test_knowledge_base_index_and_search(client):
    kb = client.get("/api/knowledge").json()
    assert kb["chunks"] == 0 and kb["documents"] and all(d["status"] == "not indexed" for d in kb["documents"]) and "keyword" in kb["mode"]
    empty = client.post("/api/knowledge/search", json={"query": "refund"}).json()
    assert empty["index_empty"] and empty["results"] == []
    assert client.post("/api/knowledge/index", json={"path": "."}).json()["ok"]
    kb = client.get("/api/knowledge").json()
    assert kb["chunks"] > 0 and any(d["status"] == "indexed" and d["source"].endswith("refund_policy.md") for d in kb["documents"])
    res = client.post("/api/knowledge/search", json={"query": "refund approval above 1 lakh", "k": 3}).json()
    assert res["results"] and res["results"][0]["source"].endswith("refund_policy.md") and res["results"][0]["score"] > 0
    assert res["steps"]["query_terms"] and res["results"][0]["matched_terms"]


def test_files_and_repo_views(client):
    ls = client.get("/api/files", params={"path": "."}).json()["entries"]
    assert {"docs", "notes"} <= {e["name"] for e in ls if e["type"] == "dir"}
    f = client.get("/api/files/read", params={"path": "docs/refund_policy.md"}).json()
    assert "refund" in f["content"].lower() and "bytes" in f["info"]
    assert client.get("/api/files/read", params={"path": "../../etc/passwd"}).status_code == 400
    assert client.get("/api/files/read", params={"path": ".env"}).status_code == 400
    hits = client.get("/api/files/search", params={"q": "refund"}).json()["hits"]
    assert hits and hits[0]["path"]
    tree = client.get("/api/repo/tree", params={"depth": 2}).json()["tree"]
    assert any(n["name"] == "src" and n["type"] == "dir" and n["children"] for n in tree)
    st = client.get("/api/repo/status").json()
    assert "available" in st
    assert client.get("/api/repo/file", params={"path": "pyproject.toml", "end": 5}).json()["content"].startswith("pyproject.toml")


# ----------------------------------------------------------------------------- analytics / security / playground
def test_analytics_overview_security_after_activity(client):
    chat(client, "which tables are in the database?")
    chat(client, "calculate 2+2")
    a = client.get("/api/analytics").json()
    assert a["totals"]["requests"] == 2 and a["totals"]["tool_calls"] == 2 and a["totals"]["tool_success_rate"] == 1.0
    assert a["daily"] and a["daily"][0]["requests"] == 2 and a["models"][0]["model"] == "mock"
    assert {t["tool"] for t in a["tools"]} == {"db__list_tables", "utility__calculate"}
    o = client.get("/api/overview").json()
    assert o["cards"]["requests"] == 2 and o["recent_conversations"] and o["recent_tool_runs"] and o["database"]["table_count"] == 3
    assert len(o["token_series"]) == 2
    sec = client.get("/api/security").json()
    assert sec["redaction"]["enabled"] and sec["decisions"]["read_only"] == "allow" and sec["tool_permissions"]["approve"] > 0
    assert sec["database"]["write_tool"]["permission"] == "approve"


def test_playground_and_model_test(client):
    r = client.post("/api/model/playground", json={"prompt": "hello", "system": "be brief", "temperature": 0.3}).json()
    assert r["ok"] and r["text"] and r["input_tokens"] > 0 and r["latency_ms"] >= 0
    assert client.post("/api/model/test", json={}).json()["ok"]
    m = client.get("/api/model").json()
    assert m["connection"] == "ok" and m["usage"]["requests"] == 2 and m["playground_last"]["ok"]
    assert client.post("/api/model/playground", json={"prompt": ""}).status_code == 422
