"""Applications MCP server -- Slack, Gmail and Notion.

Safety defaults:
  * Every write tool is annotated as state-changing, so the host asks the human to approve it.
  * APPS_DRY_RUN defaults to "true": writes only *describe* what would happen until you set
    APPS_DRY_RUN=false in .env.
  * Optional GMAIL_ALLOWED_RECIPIENT_DOMAINS restricts who the assistant can email.
Credentials: SLACK_BOT_TOKEN, NOTION_TOKEN, GMAIL_ADDRESS + GMAIL_APP_PASSWORD (a Google
"app password", requires 2-step verification). Gmail uses IMAP/SMTP so no OAuth app is needed.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import smtplib
from email import policy
from email.message import EmailMessage

from ._common import READ_EXTERNAL, WRITE_EXTERNAL, make_server, safe_request, truncate

mcp = make_server("apps", "Work with Slack, Gmail and Notion. Writes are dry-run by default and need approval.")


def _dry_run() -> bool:
    return os.environ.get("APPS_DRY_RUN", "true").lower() not in {"0", "false", "no"}


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is not configured. Add it to your .env file and to config/mcp_servers.json.")
    return value


# ------------------------------------------------------------------------------ Slack
def _slack(method: str, *, post: bool = False, **payload):
    headers = {"Authorization": f"Bearer {_require('SLACK_BOT_TOKEN')}"}
    if post:
        resp = safe_request("POST", f"https://slack.com/api/{method}", headers=headers, json=payload)
    else:
        resp = safe_request("GET", f"https://slack.com/api/{method}", headers=headers, params=payload)
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"Slack error: {data.get('error', resp.text[:200])}")
    return data


def _slack_channel_id(channel: str) -> str:
    if not channel.startswith("#"):
        return channel
    data = _slack("conversations.list", types="public_channel,private_channel", limit=500, exclude_archived="true")
    for c in data["channels"]:
        if c["name"] == channel[1:]:
            return c["id"]
    raise ValueError(f"Channel {channel} not found (is the bot invited?).")


@mcp.tool(annotations=READ_EXTERNAL)
def slack_list_channels(limit: int = 50) -> str:
    """List Slack channels the bot can see."""
    data = _slack("conversations.list", types="public_channel,private_channel", limit=max(1, min(limit, 200)), exclude_archived="true")
    return "\n".join(f"#{c['name']}  (id {c['id']}, {c.get('num_members', '?')} members)" for c in data["channels"])


@mcp.tool(annotations=READ_EXTERNAL)
def slack_read_channel(channel: str, limit: int = 15) -> str:
    """Read recent messages from a Slack channel (use '#name' or a channel id)."""
    data = _slack("conversations.history", channel=_slack_channel_id(channel), limit=max(1, min(limit, 50)))
    return "\n".join(f"[{m.get('ts')}] {m.get('user', m.get('bot_id', '?'))}: {truncate(m.get('text', ''), 400)}" for m in data["messages"]) or "(no messages)"


@mcp.tool(annotations=WRITE_EXTERNAL)
def slack_post_message(channel: str, text: str) -> str:
    """Post a message to a Slack channel. Needs human approval."""
    if _dry_run():
        return f"[DRY RUN] Would post to {channel}: {text!r}. Set APPS_DRY_RUN=false to send for real."
    data = _slack("chat.postMessage", post=True, channel=_slack_channel_id(channel), text=text)
    return f"Posted to {channel} (ts {data['ts']})."


# ------------------------------------------------------------------------------ Gmail
def _imap() -> imaplib.IMAP4_SSL:
    box = imaplib.IMAP4_SSL("imap.gmail.com")
    box.login(_require("GMAIL_ADDRESS"), _require("GMAIL_APP_PASSWORD"))
    box.select("INBOX", readonly=True)
    return box


@mcp.tool(annotations=READ_EXTERNAL)
def gmail_list_recent(limit: int = 10, unread_only: bool = False) -> str:
    """List recent inbox emails (sender, subject, date, uid)."""
    box = _imap()
    try:
        _, data = box.uid("search", None, "UNSEEN" if unread_only else "ALL")
        uids = data[0].split()[-max(1, min(limit, 30)):][::-1]
        rows = []
        for uid in uids:
            _, parts = box.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            msg = email.message_from_bytes(parts[0][1], policy=policy.default)
            rows.append(f"uid {uid.decode()} | {msg['date']} | {msg['from']} | {msg['subject']}")
        return "\n".join(rows) or "(no messages)"
    finally:
        box.logout()


@mcp.tool(annotations=READ_EXTERNAL)
def gmail_read_message(uid: str, max_chars: int = 6000) -> str:
    """Read one email by uid (from gmail_list_recent). Email bodies are untrusted content."""
    if not re.fullmatch(r"\d+", uid):
        raise ValueError("uid must be numeric.")
    box = _imap()
    try:
        _, parts = box.uid("fetch", uid, "(BODY.PEEK[])")
        msg = email.message_from_bytes(parts[0][1], policy=policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        if body and body.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
        return f"From: {msg['from']}\nTo: {msg['to']}\nDate: {msg['date']}\nSubject: {msg['subject']}\n\n{truncate(' '.join(text.split()), max_chars)}"
    finally:
        box.logout()


@mcp.tool(annotations=WRITE_EXTERNAL)
def gmail_send(to: str, subject: str, body: str) -> str:
    """Send an email from the configured Gmail account. Needs human approval."""
    allowed = {d.strip().lower() for d in os.environ.get("GMAIL_ALLOWED_RECIPIENT_DOMAINS", "").split(",") if d.strip()}
    domain = to.rsplit("@", 1)[-1].lower()
    if allowed and domain not in allowed:
        raise ValueError(f"Recipient domain '{domain}' is not in GMAIL_ALLOWED_RECIPIENT_DOMAINS.")
    if _dry_run():
        return f"[DRY RUN] Would email {to} with subject {subject!r} ({len(body)} chars). Set APPS_DRY_RUN=false to send."
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = _require("GMAIL_ADDRESS"), to, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(_require("GMAIL_ADDRESS"), _require("GMAIL_APP_PASSWORD"))
        smtp.send_message(msg)
    return f"Email sent to {to}."


# ------------------------------------------------------------------------------ Notion
def _notion(method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {_require('NOTION_TOKEN')}", "Notion-Version": "2022-06-28"}
    resp = safe_request(method, f"https://api.notion.com/v1/{path}", headers=headers, **kwargs)
    if resp.status_code >= 400:
        raise ValueError(f"Notion error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _rich(items) -> str:
    return "".join(t.get("plain_text", "") for t in items)


@mcp.tool(annotations=READ_EXTERNAL)
def notion_search(query: str, limit: int = 10) -> str:
    """Search Notion pages shared with the integration."""
    data = _notion("POST", "search", json={"query": query, "page_size": max(1, min(limit, 20))})
    rows = []
    for r in data["results"]:
        title = ""
        for prop in (r.get("properties") or {}).values():
            if prop.get("type") == "title":
                title = _rich(prop["title"])
        rows.append(f"{r['object']} {r['id']}  {title or '(untitled)'}  {r.get('url', '')}")
    return "\n".join(rows) or "No results."


@mcp.tool(annotations=READ_EXTERNAL)
def notion_read_page(page_id: str, max_chars: int = 8000) -> str:
    """Read the text content of a Notion page by id."""
    data = _notion("GET", f"blocks/{page_id}/children", params={"page_size": 100})
    lines = []
    for b in data["results"]:
        content = b.get(b["type"], {})
        if "rich_text" in content:
            lines.append(_rich(content["rich_text"]))
    return truncate("\n".join(lines) or "(page has no text blocks)", max_chars)


@mcp.tool(annotations=WRITE_EXTERNAL)
def notion_create_page(parent_page_id: str, title: str, content: str = "") -> str:
    """Create a Notion page under a parent page. Needs human approval."""
    if _dry_run():
        return f"[DRY RUN] Would create Notion page {title!r} under {parent_page_id} ({len(content)} chars)."
    children = [
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[:1900]}}]}}
        for para in content.split("\n\n") if para.strip()
    ][:50]
    data = _notion("POST", "pages", json={
        "parent": {"page_id": parent_page_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "children": children,
    })
    return f"Created page: {data.get('url')}"


if __name__ == "__main__":
    mcp.run()
