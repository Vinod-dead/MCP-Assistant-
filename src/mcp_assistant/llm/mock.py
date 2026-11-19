"""Offline 'LLM' for demos, tests and CI plumbing checks -- NOT a real model.

It maps keywords to tool calls with a tiny planner and answers by echoing tool output, so the whole
pipeline (hub, policy, approvals, audit, tracing) can be exercised without an API key. Its scores in
the eval harness only prove the plumbing works; use Gemini to measure real tool-selection accuracy.
"""
from __future__ import annotations

import re
from typing import Any

from ..models import LLMResponse, Message, ToolCall, ToolInfo, Usage

_FILE_RX = re.compile(r"[\w./\-]+\.(?:md|txt|csv|pdf|docx|json|ya?ml|py)\b", re.I)
_HELP = (
    "I'm running in offline demo mode (no Gemini key found), so I only understand simple requests. Try:\n"
    "- list the files in the workspace\n- read docs/refund_policy.md\n- which tables are in the database?\n"
    "- show overdue invoices\n- search the docs for refund policy\n- remember that I prefer INR lakhs\n"
    "- calculate 450000 * 0.18\n- what time is it?\n- show the git log\n- search the web for MCP protocol\n"
    "- post 'hello' to slack\n\nAdd GEMINI_API_KEY to .env for the real assistant."
)


def _plan(text: str) -> list[tuple[str, dict[str, Any]]]:
    t = text.lower().strip()
    m = _FILE_RX.search(text)
    if re.search(r"\bremember\b", t):
        fact = re.sub(r"(?i)^.*?\bremember( that)?\b", "", text).strip(" .") or text
        return [("memory__remember", {"fact": fact})]
    if "slack" in t and re.search(r"\b(post|send|message)\b", t):
        quoted = re.search(r"['\"“](.+?)['\"”]", text)
        return [("apps__slack_post_message", {"channel": "#general", "text": quoted.group(1) if quoted else text})]
    if re.search(r"\b(email|gmail)\b", t) and re.search(r"\bsend\b", t):
        return [("apps__gmail_send", {"to": "team@example.com", "subject": "Hello", "body": text})]
    if m and re.search(r"\b(read|open|summari[sz]e|show|what'?s in|contents?)\b", t):
        return [("files__read_file", {"path": m.group(0)})]
    if re.search(r"\b(list|show|what).{0,20}\b(files|folders|workspace|directory)\b", t):
        return [("files__list_directory", {"path": "."})]
    if re.search(r"\boverdue\b", t):
        return [("db__query", {"sql": "SELECT i.invoice_no, c.name, i.amount, i.due_date FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.status = 'overdue' ORDER BY i.amount DESC LIMIT 10"})]
    if re.search(r"\b(top|biggest|largest)\b.*\bcustomers?\b|\brevenue\b", t):
        return [("db__query", {"sql": "SELECT c.name, ROUND(SUM(i.amount), 2) AS total FROM invoices i JOIN customers c ON c.id = i.customer_id GROUP BY c.name ORDER BY total DESC LIMIT 5"})]
    if re.search(r"\b(tables?|schema|database)\b", t):
        return [("db__list_tables", {})]
    if re.search(r"\bgit\b.*\b(log|history)\b|\brecent commits?\b|\bcommit history\b", t):
        return [("repo__git_log", {"n": 5})]
    if re.search(r"\b(search|find|grep)\b.*\b(code|repo|repository|source)\b", t):
        target = re.search(r"\bfor\s+['\"`]?([A-Za-z_][\w.]*)", text)
        return [("repo__search_code", {"pattern": target.group(1) if target else "def "})]
    if re.search(r"\b(web|internet|online|latest|news)\b", t):
        q = re.sub(r"(?i)^(please )?(search|look up|find)( the web| online)?( for)?", "", text).strip() or text
        return [("web__web_search", {"query": q})]
    if re.search(r"\bcalculate\b|\bcompute\b|^what is [\d(]", t):
        expr = re.findall(r"[\d.+\-*/() ]{3,}", text)
        return [("utility__calculate", {"expression": (max(expr, key=len).strip() if expr else "1+1")})]
    if re.search(r"\b(time|date|today)\b", t):
        return [("utility__current_time", {})]
    if re.search(r"\b(bucket|cloud|gcs|s3|bigquery)\b", t):
        return [("cloud__cloud_status", {})]
    if re.search(r"\b(docs?|policy|policies|handbook|onboarding|knowledge|notes?|refund|gst)\b", t):
        return [("knowledge__index_folder", {"path": "."}), ("knowledge__search_knowledge", {"query": text, "k": 3})]
    return []


class MockLLM:
    name = "mock"

    async def generate(self, system: str, messages: list[Message], tools: list[ToolInfo]) -> LLMResponse:
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=0)
        question = messages[last_user].text if messages else ""
        done = [c for m in messages[last_user + 1 :] if m.role == "model" for c in m.tool_calls]
        plan = _plan(question)
        available = {t.qualified for t in tools}
        usage = Usage(input_tokens=sum(len(m.text) for m in messages) // 4 + len(system) // 4, output_tokens=40)

        pending = plan[len(done):]
        if pending:
            name, args = pending[0]
            if name in available:
                return LLMResponse(tool_calls=[ToolCall(id=f"mock_{len(done)}", name=name, args=args)], usage=usage)
            return LLMResponse(text=f"I don't have a tool for that in the current permission profile ({name} is not available).", usage=usage)
        if not plan:
            return LLMResponse(text=_HELP, usage=usage)

        results = [r for m in messages[last_user + 1 :] if m.role == "tool" for r in m.tool_results]
        body = "\n\n".join(f"**{r.name}**\n```text\n{r.content[:1200]}\n```" for r in results[-2:])
        return LLMResponse(text=f"(offline demo mode — raw tool output)\n\n{body}", usage=usage)
