"use client";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, Boxes, Coins, Database, Gauge, Hash, ShieldCheck, Timer, Wrench, Zap } from "lucide-react";
import Link from "next/link";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, Empty, ErrorBox, PageHeader, Stat, kindTone, statusTone } from "@/components/ui";
import { Workflow } from "@/components/workflow";
import { api } from "@/lib/api";
import { EXAMPLES, WORKFLOW_PROMPT } from "@/lib/examples";
import { ago, clock, compact, ms, num, pct, secs, short, usd } from "@/lib/format";
import { SqlView } from "@/components/sqlview";

export default function Overview() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api.get("/api/overview"), refetchInterval: 6000 });
  const d = q.data; const c = d?.cards; const h = d?.health;
  if (q.isError) return <><PageHeader title="Overview" /><ErrorBox error={q.error} onRetry={() => q.refetch()} /></>;
  return (
    <div className="space-y-5">
      <PageHeader title="Overview" sub="Live state of the MCP runtime. Every number comes from the running system; anything not recorded shows as “Unavailable”."
        actions={<Link href={`/workspace/?prompt=${encodeURIComponent(WORKFLOW_PROMPT)}`} className="btn btn-primary"><Zap className="h-4 w-4" />Run the live example</Link>} />

      <Card title="How a request flows" right={h && <Badge tone={h.offline_demo ? "warn" : "ok"} dot>{h.offline_demo ? "offline demo model" : `live · ${h.provider}`}</Badge>}>
        <Workflow model={h?.model} />
        <p className="mt-3 text-xs text-mute">The AI Workspace lights these stages up from the real event stream while a request runs. “Run the live example” sends: <span className="text-ink">“{WORKFLOW_PROMPT}”</span></p>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="MCP servers" icon={<Boxes className="h-4 w-4" />} loading={q.isLoading} value={h ? `${h.servers.up}/${h.servers.total}` : "…"} sub={h && (h.servers.up === h.servers.total ? "all running" : "some failed to start")} />
        <Stat label="Tools" icon={<Wrench className="h-4 w-4" />} loading={q.isLoading} value={num(c?.tools_total)} sub={c && `${c.tools_exposed} exposed to the model`} />
        <Stat label="Database" icon={<Database className="h-4 w-4" />} loading={q.isLoading} value={d?.database.connection ?? "…"} sub={d && `${d.database.dialect} · ${num(d.database.table_count)} tables`} />
        <Stat label="Tool success rate" icon={<ShieldCheck className="h-4 w-4" />} loading={q.isLoading} value={pct(c?.tool_success_rate)} sub="from audit log" />
        <Stat label="Requests" icon={<Hash className="h-4 w-4" />} loading={q.isLoading} value={num(c?.requests)} sub="recorded in traces.jsonl" />
        <Stat label="Tokens (in / out)" icon={<Activity className="h-4 w-4" />} loading={q.isLoading} value={c ? `${compact(c.input_tokens)} / ${compact(c.output_tokens)}` : "…"} />
        <Stat label="Avg latency" icon={<Timer className="h-4 w-4" />} loading={q.isLoading} value={secs(c?.avg_latency_s)} />
        <Stat label="Estimated cost" icon={<Coins className="h-4 w-4" />} loading={q.isLoading} value={usd(c?.cost_usd)} sub="estimate · config/pricing.yaml" />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Token usage per request" className="xl:col-span-2" right={<Link className="text-xs text-accent" href="/analytics/">Analytics <ArrowRight className="inline h-3 w-3" /></Link>}>
          {q.isLoading ? <div className="sk h-56" /> : d.token_series.length === 0 ? <Empty title="No requests recorded yet" hint="Send a message in the AI Workspace and token usage appears here." /> : (
            <div className="h-56"><ResponsiveContainer>
              <AreaChart data={d.token_series}><defs><linearGradient id="gi" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5b8cff" stopOpacity={0.5} /><stop offset="1" stopColor="#5b8cff" stopOpacity={0} /></linearGradient>
                <linearGradient id="go" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#8b7bff" stopOpacity={0.5} /><stop offset="1" stopColor="#8b7bff" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="#232a3b" vertical={false} /><XAxis dataKey="index" stroke="#8a93a8" fontSize={11} /><YAxis stroke="#8a93a8" fontSize={11} width={40} />
                <Tooltip contentStyle={{ background: "#10131c", border: "1px solid #232a3b", borderRadius: 8 }} />
                <Area dataKey="input" name="input tokens" stroke="#5b8cff" fill="url(#gi)" /><Area dataKey="output" name="output tokens" stroke="#8b7bff" fill="url(#go)" /></AreaChart></ResponsiveContainer></div>)}
        </Card>
        <Card title="MCP servers" right={<Link className="text-xs text-accent" href="/servers/">Monitor <ArrowRight className="inline h-3 w-3" /></Link>}>
          {q.isLoading ? <div className="sk h-56" /> : <ul className="space-y-1.5">{d.servers.map((s: any) => (
            <li key={s.name} className="flex items-center justify-between text-sm"><span className="font-mono">{s.name}</span><span className="flex items-center gap-2 text-xs text-mute">{s.tools} tools<Badge tone={statusTone(s.status)} dot>{s.status}</Badge></span></li>))}</ul>}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Recent tool runs" pad={false}>
          {q.isLoading ? <div className="p-4"><div className="sk h-24" /></div> : d.recent_tool_runs.length === 0 ? <Empty title="No tool runs yet" hint="Tools run when the assistant needs them, or from the MCP Tools page." /> :
            <ul className="divide-y divide-line">{d.recent_tool_runs.map((r: any, i: number) => (
              <li key={i} className="flex items-center justify-between gap-3 px-4 py-2 text-sm"><span className="truncate font-mono text-accent">{r.tool}</span><span className="flex shrink-0 items-center gap-2 text-xs text-mute">{ms(r.ms)}<Badge tone={r.ok ? "ok" : "bad"}>{r.ok ? "ok" : r.status}</Badge>{ago(r.ts)}</span></li>))}</ul>}
        </Card>
        <Card title="Database activity" right={<Link className="text-xs text-accent" href="/database/">Explorer <ArrowRight className="inline h-3 w-3" /></Link>}>
          {q.isLoading ? <div className="sk h-24" /> : <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs"><Badge tone="ok">read-only connection</Badge><Badge>{num(d.database.total_rows)} rows total</Badge><Badge>last query OK: {d.database.last_successful_query ? ago(d.database.last_successful_query) : "Unavailable"}</Badge></div>
            {d.database.recent_queries.length === 0 && d.database.recent_mcp_db_calls.length === 0 ? <Empty title="No queries yet" hint="Run SQL in the Database Explorer, or ask the assistant about your data." /> :
              d.database.recent_queries.slice(0, 3).map((x: any, i: number) => <div key={i} className="mb-2 rounded-lg border border-line bg-bg p-2"><SqlView sql={short(x.sql, 160)} /><div className="mt-1 text-[11px] text-mute">{x.ok ? `${x.rows} rows` : "failed"} · {ms(x.ms)} · {ago(x.ts)}</div></div>)}</>}
        </Card>
      </div>

      <Card title="Try an example" right={<span className="text-xs text-mute">each runs real MCP tools</span>}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{EXAMPLES.map((e) => (
          <Link key={e.title} href={`/workspace/?prompt=${encodeURIComponent(e.prompt)}`} className="group rounded-lg border border-line bg-panel2/50 p-3 transition hover:border-accent/50 hover:bg-panel2">
            <div className="flex items-center justify-between"><span className="text-sm font-medium">{e.title}</span><ArrowRight className="h-3.5 w-3.5 text-mute transition group-hover:translate-x-0.5 group-hover:text-accent" /></div>
            <p className="mt-1 text-xs text-mute">{e.prompt}</p><div className="mt-2 flex flex-wrap gap-1">{e.tools.map((t) => <span key={t} className="rounded bg-bg px-1.5 py-0.5 font-mono text-[10.5px] text-accent">{t}</span>)}</div>
          </Link>))}</div>
      </Card>

      <Card title="Recent audit events" pad={false}>
        {q.isLoading ? <div className="p-4"><div className="sk h-20" /></div> : d.recent_audit.length === 0 ? <Empty title="Audit log is empty" /> :
          <ul className="divide-y divide-line">{d.recent_audit.map((e: any, i: number) => <li key={i} className="flex items-center gap-3 px-4 py-1.5 text-xs"><span className="w-16 font-mono text-mute">{clock(e.ts)}</span><span className="font-mono">{e.tool ?? e.event}</span><Badge tone={statusTone(e.status)}>{e.status}</Badge></li>)}</ul>}
      </Card>
    </div>
  );
}
