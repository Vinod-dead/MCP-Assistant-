"use client";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, Empty, ErrorBox, PageHeader, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { compact, num, pct, secs, usd } from "@/lib/format";

const TT = { contentStyle: { background: "#10131c", border: "1px solid #232a3b", borderRadius: 8, fontSize: 12 } };
const AX = { stroke: "#8a93a8", fontSize: 11 };
const PAL = ["#5b8cff", "#8b7bff", "#34d399", "#fbbf24", "#f87171", "#22d3ee", "#f472b6", "#a3e635"];

export default function Analytics() {
  const q = useQuery({ queryKey: ["analytics"], queryFn: () => api.get("/api/analytics"), refetchInterval: 10000 });
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data; const t = d?.totals;
  const none = d && d.requests.length === 0 && d.tools.length === 0;
  return (
    <div className="space-y-5">
      <PageHeader title="Analytics" sub="Built only from what was recorded in logs/traces.jsonl and logs/audit.jsonl. Nothing is estimated or back-filled." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
        <Stat label="Requests" value={num(t?.requests)} loading={!d} /><Stat label="Input tokens" value={compact(t?.input_tokens)} loading={!d} /><Stat label="Output tokens" value={compact(t?.output_tokens)} loading={!d} />
        <Stat label="Avg latency" value={secs(t?.avg_latency_s)} loading={!d} sub={t && `p95 ${secs(t.p95_latency_s)}`} /><Stat label="Est. cost" value={usd(t?.cost_usd)} loading={!d} /><Stat label="Tool success" value={pct(t?.tool_success_rate)} loading={!d} sub={t && `${t.tool_calls} executed calls`} />
      </div>
      {d?.coverage.note && <p className="rounded-lg border border-line bg-panel2/50 p-3 text-xs text-mute">{d.coverage.note}</p>}
      {none ? <Card><Empty title="No analytics data yet" hint="Use the AI Workspace — every request is traced and every tool call audited, then charted here." /></Card> : <>
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Tokens per request">{!d ? <div className="sk h-56" /> : <div className="h-56"><ResponsiveContainer><BarChart data={d.requests}><CartesianGrid stroke="#232a3b" vertical={false} /><XAxis dataKey="index" {...AX} /><YAxis {...AX} width={40} /><Tooltip {...TT} /><Bar dataKey="input_tokens" name="input" stackId="a" fill="#5b8cff" /><Bar dataKey="output_tokens" name="output" stackId="a" fill="#8b7bff" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>}</Card>
          <Card title="Latency per request (s)">{!d ? <div className="sk h-56" /> : <div className="h-56"><ResponsiveContainer><LineChart data={d.requests}><CartesianGrid stroke="#232a3b" vertical={false} /><XAxis dataKey="index" {...AX} /><YAxis {...AX} width={40} /><Tooltip {...TT} /><Line dataKey="latency_s" name="seconds" stroke="#34d399" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>}</Card>
          <Card title="Most-used tools" right={<span className="text-xs text-mute">executed calls</span>}>{!d ? <div className="sk h-56" /> : d.tools.length === 0 ? <Empty title="No tool calls yet" /> : <div className="h-64"><ResponsiveContainer><BarChart data={d.tools.slice(0, 8)} layout="vertical" margin={{ left: 50 }}><CartesianGrid stroke="#232a3b" horizontal={false} /><XAxis type="number" {...AX} allowDecimals={false} /><YAxis type="category" dataKey="tool" {...AX} width={150} /><Tooltip {...TT} /><Bar dataKey="ok" stackId="a" fill="#34d399" name="ok" /><Bar dataKey="errors" stackId="a" fill="#f87171" name="errors" /><Bar dataKey="blocked" stackId="a" fill="#fbbf24" name="blocked" /></BarChart></ResponsiveContainer></div>}</Card>
          <Card title="Calls by MCP server">{!d ? <div className="sk h-56" /> : d.servers.length === 0 ? <Empty title="No server activity yet" /> : <div className="h-64"><ResponsiveContainer><PieChart><Pie data={d.servers} dataKey="calls" nameKey="server" innerRadius={55} outerRadius={90} paddingAngle={2}>{d.servers.map((_: any, i: number) => <Cell key={i} fill={PAL[i % PAL.length]} stroke="#10131c" />)}</Pie><Tooltip {...TT} /></PieChart></ResponsiveContainer><div className="flex flex-wrap justify-center gap-2 text-xs">{d.servers.map((s: any, i: number) => <span key={s.server} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: PAL[i % PAL.length] }} />{s.server}</span>)}</div></div>}</Card>
        </div>
        {d && d.daily.length > 0 && <Card title="Per day" pad={false}><Table head={["Date", "Requests", "In", "Out", "Avg latency", "Cost"]}>{d.daily.map((r: any) => <tr key={r.date}><td className="td">{r.date}</td><td className="td">{r.requests}</td><td className="td">{num(r.input_tokens)}</td><td className="td">{num(r.output_tokens)}</td><td className="td">{secs(r.avg_latency_s)}</td><td className="td">{usd(r.cost_usd)}</td></tr>)}</Table></Card>}
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Tool reliability" pad={false}>{!d || d.tools.length === 0 ? <Empty title="No data" /> : <Table head={["Tool", "Calls", "OK", "Errors", "Blocked", "Error rate"]}>{d.tools.map((r: any) => <tr key={r.tool}><td className="td">{r.tool}</td><td className="td">{r.calls}</td><td className="td">{r.ok}</td><td className="td">{r.errors}</td><td className="td">{r.blocked}</td><td className="td">{pct(r.error_rate)}</td></tr>)}</Table>}</Card>
          <Card title="Per model" pad={false}>{!d || d.models.length === 0 ? <Empty title="No data" /> : <Table head={["Model", "Requests", "In", "Out", "Cost"]}>{d.models.map((r: any) => <tr key={r.model}><td className="td">{r.model === "unknown" ? <Badge>unrecorded</Badge> : r.model}</td><td className="td">{r.requests}</td><td className="td">{num(r.input_tokens)}</td><td className="td">{num(r.output_tokens)}</td><td className="td">{usd(r.cost_usd)}</td></tr>)}</Table>}</Card>
        </div></>}
    </div>
  );
}
