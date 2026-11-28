# MCP Assistant + Studio

An AI assistant that connects to your **files, databases, code, cloud, apps, the web and any API** through the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io) — with permissions, human approval, an audit log,
metrics and an eval harness built around it. Python, runs in VS Code, talks to **NVIDIA NIM** (HTTPX, no OpenAI SDK) or **Gemini**, or runs offline with a mock model. It has two front doors that share one runtime: a **CLI** and the **MCP Assistant Studio** web dashboard.

```
                        ┌───────────────────────── host (this repo) ─────────────────────────┐
  you ──► CLI / VS Code │  Agent loop (ReAct)  ──►  Policy (allow / approve / deny)          │
                        │   │  memory + RAG ctx        │      Audit log · Secret redaction    │
                        │   ▼                          ▼      Injection scan · Budgets        │
                        │  LLM (NVIDIA|Gemini|mock)    MCP Hub  (parallel stdio clients)         │
                        │  Metrics: tokens, tok/s, p95, $/request                             │
                        └──────────────────────────────┬─────────────────────────────────────┘
        ┌────────┬────────┬────────┬────────┬──────────┼─────────┬────────┬──────────┬────────┐
      files     db      repo    cloud     apps        web       api    utility   knowledge  memory   … any MCP server
   (sandbox) (SQL,ro) (git,GH) (GCP/AWS/ (Slack/      (search,  (allow-  (calc,    (hybrid    (facts
                                Azure)   Gmail/Notion) fetch)   listed)  time)      RAG)     across sessions)
```

## What's from the poster vs. what I added

| Poster block | Server | What it does |
|---|---|---|
| Files & Documents | `files` | list / read (txt, md, csv, code, **PDF, DOCX**) / search / write, locked to one folder |
| Databases | `db` | schema browsing + read-only SQL on SQLite (demo DB included), PostgreSQL & MySQL via `DATABASE_URL`; guarded `INSERT/UPDATE` |
| Code Repositories | `repo` | tree, read, regex search, `git log/diff/status`, GitHub issues (list / create) |
| Cloud Services | `cloud` | Google Cloud Storage + **BigQuery (cost-capped)**, AWS S3, Azure Blob — read-only |
| Applications | `apps` | **Slack**, **Gmail** (IMAP/SMTP), **Notion** — writes are dry-run by default |
| Web Search | `web` | DuckDuckGo search (no key) + page fetch with SSRF protection |
| APIs | `api` | `GET` and approval-gated `POST/PUT/PATCH/DELETE` to **allowlisted** hosts; tokens injected server-side |
| Other Tools | `utility` + any MCP server | safe calculator, timezone clock; add third-party servers in `config/mcp_servers.json` |
| *Secure & controlled access* | `policy.py` | profiles `readonly` / `standard` / `admin`, per-tool rules, human approval, rate + step + cost budgets |
| *Understands your context* | `memory`, `knowledge` | long-term memory injected into every prompt; **hybrid RAG** (BM25 + Gemini embeddings, RRF) over your docs |
| *Takes real actions* | write tools | create files, rows, issues, Slack/Notion/email — each gated by policy |
| *Accurate & up to date* | `web`, `api`, `cloud` | live data, with the source named in answers |

**Built from scratch, beyond the poster:** BM25 + reciprocal-rank-fusion retrieval, the policy engine, audit log,
secret redaction, prompt-injection scanner, read-only SQL guard, per-turn tracing/metrics (tokens/sec, p50/p95,
cost per request), optional self-reflection pass, and a golden-set eval gate for CI.

## Quick start (VS Code)

1. Install **Python 3.10+** and open this folder in VS Code (`File → Open Folder`).
2. Create the environment — `Terminal → Run Task → Setup: create .venv and install`, or by hand:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
   Pick the `.venv` interpreter when VS Code asks (`Ctrl+Shift+P → Python: Select Interpreter`).
3. **Try it with no API key:** press `F5` → *Assistant (offline mock, no API key)*. (A keyword router stands in for the model so you can see tools, approvals and the audit log working.)
4. **Real assistant:** copy `.env.example` to `.env` and set `NVIDIA_API_KEY` (default model `nvidia/nemotron-3.5-lightning-30b-a3b`, override with `NVIDIA_MODEL`) **or** `GEMINI_API_KEY`. With `--provider auto` NVIDIA is preferred when its key exists. Gemini key ([get one](https://aistudio.google.com/apikey)), press `F5` → *Assistant (Gemini …)*.
   - Model default is `gemini-3.6-flash`. Model names change often — run `python -m mcp_assistant.cli --list-models` and set `GEMINI_MODEL` in `.env` if needed.
   - Vertex AI instead of a key: see the comments in `.env.example`.
5. Or from any terminal: `python -m mcp_assistant.cli` (also installed as `mcp-assistant`).

Things to try:
```
which tables are in the database?
show overdue invoices, biggest first, and total them in INR lakhs
what approval is needed for a refund above 1 lakh?        (RAG over workspace/docs)
read notes/vendor_email_dump.txt and summarize it          (security demo: contains an injection attempt)
post "report ready" to #finance-ops on Slack               (asks approval; dry-run until APPS_DRY_RUN=false)
remember that I prefer amounts in INR lakhs
```
In the chat: `/tools` `/servers` `/stats` `/audit` `/memory` `/policy` `/reset` `/quit`.
Flags: `--profile readonly|standard|admin`, `--reflect` (self-check answers against tool output), `--auto-approve` (still audited), `--once "prompt"`.

You can also use the same servers directly from **VS Code's own MCP support** (`.vscode/mcp.json`, e.g. Copilot agent mode); it launches them with `python`, so start VS Code with the venv active or edit the `command`.

## MCP Assistant Studio (web dashboard)

A dark developer-tool dashboard over the **same** runtime the CLI uses — one MCP hub, one policy engine, one audit log. The CLI is untouched and still works.

```bash
pip install -e ".[dev]"
mcp-assistant-studio                    # or: python -m mcp_assistant.studio   (opens http://localhost:8765)
mcp-assistant-studio --provider mock    # no API key: plumbing is real, the model is a keyword stand-in
```
VS Code: `F5` → *Studio web UI (auto provider)* / *(offline mock)*. Node.js is **not** needed to run it — the built dashboard ships in `src/mcp_assistant/studio/web`.

| Page | What is real |
|---|---|
| Overview | health, 10 servers / tools discovered live, tokens, latency, cost estimate, request-pipeline diagram, example prompts |
| AI Workspace | streaming chat (SSE), live tool-call timeline, stop / regenerate, history search, context + memory panel, approvals |
| Model Lab | active model, connection test, playground, latency/tokens/cost measured from real calls |
| Database Explorer | tables, paging/sort/search, read-only SQL with highlighting, schema, ER diagram, history |
| MCP Tools | registry discovered from the running servers, schema-driven run form, read / write / destructive badges |
| Server Monitor | per-server status, calls, errors, latency, MCP ping, restart |
| Memory · Knowledge · Repository & Files | the real memory / RAG / git / file tools, with retrieval traces and diffs |
| Analytics · Security & Audit · Settings | charts built from `logs/*.jsonl`, policy and approval history, profile switching (lower-only), env *set / not set* |

**Rules the dashboard follows**
- API keys and connection strings never reach the browser (Settings shows only whether each variable is set).
- Anything not recorded shows **“Unavailable”** — no invented metrics, no hardcoded tool list, no claimed context-window size or benchmarks.
- Every tool call from the UI goes through the same policy → approval → redaction → audit path as the agent. The SQL tab is read-only; writes exist only as the approval-gated `db__execute_write` tool.
- Local only: binds to 127.0.0.1, per-run session token, Host/Origin checks, JSON-only writes. Privileges can be lowered at runtime, never raised.
- One runtime for all requests, a single turn lock (a second chat request gets HTTP 409), stop/cancel with history rollback.

**Developing the frontend**
```bash
cd frontend && npm install
npm run dev                 # http://localhost:3000 ; start the API with: mcp-assistant-studio --dev --no-browser
npm run typecheck && npm test
npm run build && cd .. && python scripts/sync_frontend.py   # refresh the bundled dashboard
```
Stack: Next.js 14 (App Router, static export) · TypeScript · Tailwind 3 · Lucide · Framer Motion · Recharts · React Query. Tailwind 3 was chosen on purpose (pure JS, no native binaries).

**Known limitations (honest list)**
- Live NVIDIA streaming is tested against a simulated server only; try it with your key and use *Model Lab → Test connection*.
- If the model emits invalid tool-call JSON the NVIDIA adapter raises and the turn fails (pre-existing behaviour, now shown as an error in the UI).
- Memory has no in-place edit (delete + re-add). Embeddings need Gemini credentials; otherwise retrieval is keyword-only (BM25).
- The pipeline diagram is driven by real events, but only the stages the run actually touched are meaningful (e.g. no *Database* stage for a calculator call).
- Single-user, single-process: not designed for multi-user hosting.

## Security model (read this before connecting real accounts)

- **Least privilege by construction.** MCP servers are separate processes that only receive the env vars listed for them in `config/mcp_servers.json` — the `db` server never sees your Slack token. `.env` is read by the host only.
- **Permissions come from tool metadata.** Each tool declares MCP annotations (`readOnlyHint`, `destructiveHint`). The `standard` profile auto-runs reads and **asks you** before anything else; tools a profile denies are hidden from the model entirely. Third-party tools without annotations are treated as destructive (MCP spec default), so they require approval.
- **Every call is audited** to `logs/audit.jsonl` (args are secret-redacted); per-turn traces go to `logs/traces.jsonl`.
- **Sandboxes:** file tools can't leave `FILES_ROOT` (symlink and `..` escapes blocked; `.env`/keys unreadable; no writing scripts). SQL runs on a read-only connection *and* a keyword guard. `fetch_url`/`api_*` block private, loopback and metadata addresses on every redirect hop, and `api_*` only talk to `API_ALLOWLIST` hosts.
- **Prompt injection:** tool output is wrapped as untrusted data, scanned for instruction-like text (flagged in the UI and to the model), and secrets are masked before the model sees them.
- **Safe defaults:** Slack/Gmail/Notion writes are dry-run until you set `APPS_DRY_RUN=false`; Gmail can be limited to your own domains.
- **Honest limits.** The injection scanner and SQL keyword guard are heuristics, not guarantees. For PostgreSQL/MySQL use a database user that only has `SELECT`. Keep tokens scoped (read-only Slack/Notion scopes if you don't need writes). Use the `readonly` profile when you don't need actions.

## Configuration

- `config/mcp_servers.json` — same shape as Claude Desktop / VS Code configs. Add any MCP server:
  ```json
  "my_tool": { "command": "npx", "args": ["-y", "some-mcp-server"], "env": { "TOKEN": "${MY_TOKEN}" } }
  ```
  Its tools appear as `my_tool__<name>` and go through the same policy, audit and redaction.
- `config/policy.yaml` — profiles, per-tool rules (`fnmatch` globs), step / tool-call / cost / rate limits.
- `config/pricing.yaml` — **placeholder prices**; edit them to your provider's real rates (NVIDIA currently falls back to the Gemini placeholder prices, so cost figures are estimates only) so cost-per-request is meaningful.
- Cloud extras: `pip install -e ".[gcp,aws,azure]"`; databases: `".[postgres]"` / `".[mysql]"`.

## Evaluate and gate regressions

```bash
python -m mcp_assistant.evaluate --provider gemini --min-tool-acc 0.9 --max-cost 0.01
```
Runs `eval/golden.yaml` (13 tasks: tool selection, answer facts, a prompt-injection case, an approval case) in an isolated data
directory and reports tool-selection accuracy, pass rate, p50/p95 latency, tokens and cost per request; exits non-zero below your
thresholds, so it drops straight into CI (`.github/workflows/ci.yml`). **`--provider mock` only proves the plumbing works** — measure real accuracy with Gemini.

## Project layout

```
src/mcp_assistant/
  cli.py  agent.py  runtime.py  hub.py        host: REPL, ReAct loop, wiring, MCP client hub
  policy.py  security.py  audit.py  tracing.py  governance + observability
  retrieval.py  memory.py  docs.py            BM25/RRF hybrid RAG, long-term memory, PDF/DOCX extraction
  llm/{nvidia,gemini,mock}.py                 providers (nvidia = plain HTTPX; add others by implementing `generate`)
  studio/                                     FastAPI JSON/SSE API + serves the built dashboard (studio/web)
  servers/*.py                                the 10 MCP servers (run standalone: python -m mcp_assistant.servers.db_server)
frontend/                                   Next.js dashboard source (static export -> studio/web)
scripts/sync_frontend.py                    copies frontend/out into the Python package
config/  workspace/  eval/  tests/  .vscode/
```

## What has and hasn't been verified

Verified here (72 Python tests + 7 frontend unit tests + manual runs; counts as of this build): all 10 servers start over stdio and expose 52 tools; policy profiles, approval
(declined/approved), dry-run writes, audit log; SQL guard, path sandbox, SSRF guard, git option-injection guard, injection flagging;
BM25 + fusion retrieval; the Gemini adapter against the SDK's real request/response types (schema conversion, history replay,
parsing) using stubbed responses; the golden eval gate.

**Not verified (no network/credentials in my build environment):** a live NVIDIA call (the HTTPX adapter and its SSE streaming are tested against a simulated server only), a live Gemini call, live Gemini embeddings, web search, public
URL fetch, and real Slack / Gmail / Notion / GCP / AWS / Azure / GitHub calls. These follow each service's documented API but expect
to fix small issues on first contact (the server logs are in `logs/server-<name>.log`). Tested on Python 3.13; written for 3.10+.

## Troubleshooting

- *"No NVIDIA credentials found" / "No Gemini credentials found"* → add `NVIDIA_API_KEY` or `GEMINI_API_KEY` to `.env`, or use `--provider mock`.
- *Model not found / 404* → `python -m mcp_assistant.cli --list-models`, then set `GEMINI_MODEL`.
- *A server shows red at startup* → open `logs/server-<name>.log`.
- *Want a clean demo database* → `python scripts/seed_demo_data.py`.
