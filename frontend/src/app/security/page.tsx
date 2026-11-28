"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, Lock, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, KV, PageHeader, Table, Tabs, permTone, statusTone } from "@/components/ui";
import { api } from "@/lib/api";
import { clock, ago, short } from "@/lib/format";

export default function Security() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["security"], queryFn: () => api.get("/api/security"), refetchInterval: 8000 });
  const [filter, setFilter] = useState({ status: "", tool: "" }); const [tab, setTab] = useState<"audit" | "events" | "approvals">("audit");
  const audit = useQuery({ queryKey: ["audit", filter], queryFn: () => api.get(`/api/audit?limit=100&status=${filter.status}&tool=${encodeURIComponent(filter.tool)}`), refetchInterval: 8000 });
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Security & Audit" sub="The existing policy engine, shown as-is. This page can inspect it and lower privileges — it can never bypass an approval." />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Permission profile" right={s && <Badge tone="violet">{s.profile}</Badge>}>{!s ? <div className="sk h-32" /> : <><p className="mb-3 text-xs text-mute">{s.description}</p><KV k="Read-only tools" v={<Badge tone={permTone(s.decisions.read_only)}>{s.decisions.read_only}</Badge>} /><KV k="State-changing tools" v={<Badge tone={permTone(s.decisions.state_changing)}>{s.decisions.state_changing}</Badge>} /><KV k="Destructive tools" v={<Badge tone={permTone(s.decisions.destructive)}>{s.decisions.destructive}</Badge>} />
          <div className="mt-3 flex gap-2 text-xs"><Badge tone="ok">{s.tool_permissions.allow} allowed</Badge><Badge tone="warn">{s.tool_permissions.approve} need approval</Badge><Badge tone="bad">{s.tool_permissions.deny} blocked</Badge></div></>}</Card>
        <Card title="Protections">{!s ? <div className="sk h-32" /> : <ul className="space-y-2 text-sm">
          <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" /><span>Secret redaction <span className="text-mute">({s.redaction.secret_patterns} patterns) on tool output, audit args and dashboard views</span></span></li>
          <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" /><span>Prompt-injection heuristics <span className="text-mute">({s.injection_scan.patterns} patterns) flag suspicious tool output</span></span></li>
          <li className="flex gap-2"><Lock className="mt-0.5 h-4 w-4 shrink-0 text-ok" /><span>Database: read-only connection · {s.database.sql_guard}</span></li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" /><span>Browser never receives API keys; localhost-only, per-run session token, origin & host checks</span></li></ul>}</Card>
        <Card title="Limits & write path">{!s ? <div className="sk h-32" /> : <>{Object.entries(s.limits).map(([k, v]) => <KV key={k} k={k.replace(/_/g, " ")} v={String(v)} />)}{s.database.write_tool && <div className="mt-3 rounded-lg border border-line bg-bg/60 p-2 text-xs"><span className="font-mono text-accent">{s.database.write_tool.name}</span> → <Badge tone={permTone(s.database.write_tool.permission)}>{s.database.write_tool.permission}</Badge></div>}</>}</Card>
      </div>
      {s && s.rules.length > 0 && <Card title="Explicit rules (first match wins)"><div className="flex flex-wrap gap-2">{s.rules.map((r: any, i: number) => <span key={i} className="rounded-lg border border-line bg-bg px-2 py-1 font-mono text-xs">{r.match} → <span className={r.action === "deny" ? "text-bad" : r.action === "approve" ? "text-warn" : "text-ok"}>{r.action}</span></span>)}</div></Card>}
      <Tabs value={tab} onChange={setTab} items={[{ id: "audit", label: "Audit log" }, { id: "events", label: `Security events${s ? ` (${s.security_events.length})` : ""}` }, { id: "approvals", label: "Approvals" }]} />
      {tab === "audit" && <Card pad={false} title="logs/audit.jsonl" right={<div className="flex gap-2"><select className="input w-auto" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })} aria-label="Status filter"><option value="">any status</option>{["ok", "error", "denied", "declined", "rate_limited"].map((x) => <option key={x}>{x}</option>)}</select><input className="input w-40" placeholder="tool…" value={filter.tool} onChange={(e) => setFilter({ ...filter, tool: e.target.value })} /></div>}>
        {audit.isLoading ? <div className="p-4"><div className="sk h-32" /></div> : audit.data?.events.length === 0 ? <Empty title="No audit events match" /> : <Table head={["Time", "Event", "Tool", "Status", "Source", "Decision", "Latency", "Args (redacted)"]}>{audit.data.events.map((e: any, i: number) => <tr key={i}><td className="td">{clock(e.ts)}</td><td className="td">{e.event}</td><td className="td text-accent">{e.tool ?? ""}</td><td className="td"><Badge tone={statusTone(e.status)}>{e.status}</Badge></td><td className="td">{e.source ?? "chat"}</td><td className="td">{e.decision ?? ""}{e.approved === true ? " ✓" : e.approved === false ? " ✗" : ""}</td><td className="td">{e.ms ?? ""}</td><td className="td max-w-[260px] truncate" title={JSON.stringify(e.args)}>{e.args ? short(JSON.stringify(e.args), 70) : ""}</td></tr>)}</Table>}</Card>}
      {tab === "events" && <Card pad={false}>{!s || s.security_events.length === 0 ? <Empty icon={<Eye className="h-7 w-7" />} title="No security events" hint="Blocked calls, declined approvals, injection flags and failures appear here." /> : <Table head={["When", "Tool / event", "Status", "Why flagged"]}>{s.security_events.map((e: any, i: number) => <tr key={i}><td className="td">{ago(e.ts)}</td><td className="td">{e.tool ?? e.event}</td><td className="td"><Badge tone={statusTone(e.status)}>{e.status}</Badge></td><td className="td whitespace-normal">{e.reasons.join(" · ")}</td></tr>)}</Table>}</Card>}
      {tab === "approvals" && <Card pad={false} title="Approval history">{!s || s.approvals.history.length === 0 ? <Empty title="No approvals yet" hint="When a tool needs your approval, the decision is recorded here." /> : <Table head={["When", "Tool", "Decision", "Source"]}>{s.approvals.history.map((a: any, i: number) => <tr key={i}><td className="td">{ago(a.ts ?? a.decided_at)}</td><td className="td">{a.tool}</td><td className="td"><Badge tone={a.decision === "approved" || a.allowed ? "ok" : "bad"}>{a.decision ?? (a.allowed ? "approved" : "declined")}</Badge></td><td className="td">{a.source}</td></tr>)}</Table>}</Card>}
      <button className="hidden" onClick={() => qc.invalidateQueries()} />
    </div>
  );
}
