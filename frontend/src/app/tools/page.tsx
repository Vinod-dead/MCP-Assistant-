"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Play, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Card, Empty, ErrorBox, Json, KV, PageHeader, Spinner, Tabs, cx, kindTone, permTone } from "@/components/ui";
import { api } from "@/lib/api";
import { UNAVAILABLE, ago, ms } from "@/lib/format";

function defaults(params: any[]) {
  const o: Record<string, string> = {};
  params.forEach((p) => { o[p.name] = p.default !== null && p.default !== undefined ? String(p.default) : ""; });
  return o;
}
function coerce(params: any[], vals: Record<string, string>) {
  const out: Record<string, any> = {};
  for (const p of params) {
    const v = vals[p.name];
    if (v === "" || v === undefined) { if (p.required) throw new Error(`“${p.name}” is required`); continue; }
    if (p.type === "integer") { const n = parseInt(v, 10); if (Number.isNaN(n)) throw new Error(`“${p.name}” must be an integer`); out[p.name] = n; }
    else if (p.type === "number") { const n = Number(v); if (Number.isNaN(n)) throw new Error(`“${p.name}” must be a number`); out[p.name] = n; }
    else if (p.type === "boolean") out[p.name] = v === "true";
    else out[p.name] = v;
  }
  return out;
}

export default function Tools() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tools"], queryFn: () => api.get("/api/tools"), refetchInterval: 10000 });
  const hist = useQuery({ queryKey: ["tool-history"], queryFn: () => api.get("/api/tools/history?limit=40"), refetchInterval: 6000 });
  const [filter, setFilter] = useState(""); const [server, setServer] = useState("all"); const [kind, setKind] = useState("all");
  const [sel, setSel] = useState<string | null>(null); const [vals, setVals] = useState<Record<string, string>>({}); const [tab, setTab] = useState<"run" | "schema" | "history">("run");
  const [formErr, setFormErr] = useState<string | null>(null);
  useEffect(() => { const t = new URLSearchParams(window.location.search).get("tool"); if (t) setSel(t); }, []);
  const tools: any[] = q.data?.tools ?? [];
  const shown = useMemo(() => tools.filter((t) => (server === "all" || t.server === server) && (kind === "all" || t.kind === kind) && (!filter || (t.name + t.description).toLowerCase().includes(filter.toLowerCase()))), [tools, filter, server, kind]);
  const cur = tools.find((t) => t.name === sel);
  useEffect(() => { if (cur) { setVals(defaults(cur.params)); setFormErr(null); } }, [sel, q.data?.total]); // eslint-disable-line
  const run = useMutation({
    mutationFn: (body: any) => api.post("/api/tools/execute", body),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["tools"] }); qc.invalidateQueries({ queryKey: ["tool-history"] }); },
  });
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const byServer = tools.reduce((a: any, t) => ((a[t.server] = (a[t.server] ?? 0) + 1), a), {});
  return (
    <div className="space-y-5">
      <PageHeader title="MCP Tools" sub={q.data ? `${q.data.total} tools discovered live from ${q.data.servers.length} servers — the list is read from the running runtime, not hardcoded.` : "Discovering tools…"} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <Card pad={false} title="Registry" right={<span className="text-xs text-mute">{shown.length} shown</span>}>
          <div className="flex flex-wrap gap-2 border-b border-line p-3">
            <input className="input min-w-[160px] flex-1" placeholder="Filter tools…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter tools" />
            <select className="input w-auto" value={server} onChange={(e) => setServer(e.target.value)} aria-label="Server"><option value="all">All servers</option>{Object.keys(byServer).sort().map((s) => <option key={s} value={s}>{s} ({byServer[s]})</option>)}</select>
            <select className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind"><option value="all">All kinds</option><option value="read">read-only</option><option value="write">write</option><option value="destructive">destructive</option></select>
          </div>
          <div className="max-h-[640px] overflow-y-auto">
            {q.isLoading ? <div className="space-y-2 p-3">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="sk h-10" />)}</div> : shown.length === 0 ? <Empty title="No tools match" /> : shown.map((t) => (
              <button key={t.name} onClick={() => { setSel(t.name); setTab("run"); run.reset(); }} className={cx("flex w-full items-start gap-3 border-b border-line/60 px-4 py-2.5 text-left transition hover:bg-panel2", sel === t.name && "bg-accent/10")}>
                <div className="min-w-0 flex-1"><div className="truncate font-mono text-[13px] text-accent">{t.name}</div><div className="truncate text-xs text-mute">{t.description}</div></div>
                <div className="flex shrink-0 flex-col items-end gap-1"><Badge tone={kindTone(t.kind)}>{t.kind === "read" ? "read-only" : t.kind}</Badge>{t.permission !== "allow" && <Badge tone={permTone(t.permission)}>{t.permission === "approve" ? "needs approval" : "blocked"}</Badge>}</div>
              </button>))}
          </div>
        </Card>

        <Card title={cur ? <span className="font-mono">{cur.name}</span> : "Tool details"} right={cur && <Tabs value={tab} onChange={setTab} items={[{ id: "run", label: "Run" }, { id: "schema", label: "Schema" }, { id: "history", label: "History" }]} />}>
          {!cur ? <Empty title="Select a tool" hint="Run it with real arguments, inspect its schema, or see its execution history." /> : <div className="space-y-4">
            <p className="text-sm text-mute">{cur.description}</p>
            <div className="flex flex-wrap gap-2"><Badge tone={kindTone(cur.kind)}>{cur.kind === "read" ? "read-only" : cur.kind + " operation"}</Badge><Badge tone={permTone(cur.permission)}>{cur.permission === "allow" ? "runs without approval" : cur.permission === "approve" ? "requires your approval" : "blocked by policy"}</Badge><Badge>{cur.server}</Badge>{cur.open_world && <Badge tone="warn">reaches external services</Badge>}<Badge tone={cur.exposed_to_model ? "info" : "mute"}>{cur.exposed_to_model ? "visible to model" : "hidden from model"}</Badge></div>
            {tab === "run" && (cur.permission === "deny" ? <div className="flex items-center gap-2 rounded-lg border border-bad/30 bg-bad/5 p-3 text-sm text-bad"><Lock className="h-4 w-4" />Blocked by the “{cur.permission_reason}” rule in the current permission profile. Change the profile in Settings (only downward from the startup profile; raising needs a restart).</div> : <>
              {cur.permission === "approve" && <div className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/5 p-3 text-sm text-warn"><ShieldAlert className="h-4 w-4" />Running this opens an approval dialog first. Nothing executes until you approve.</div>}
              <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); try { const args = coerce(cur.params, vals); setFormErr(null); run.mutate({ name: cur.name, args }); } catch (err: any) { setFormErr(err.message); } }}>
                {cur.params.length === 0 && <p className="text-sm text-mute">No arguments.</p>}
                {cur.params.map((p: any) => (
                  <div key={p.name}><label className="label mb-1 flex gap-2">{p.name}<span className="normal-case text-mute/70">{p.type}{p.required ? " · required" : ""}</span></label>
                    {p.enum ? <select className="input" value={vals[p.name] ?? ""} onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })}>{!p.required && <option value="" />}{p.enum.map((o: string) => <option key={o}>{o}</option>)}</select>
                      : p.type === "boolean" ? <select className="input" value={vals[p.name] ?? ""} onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })}><option value="" /><option>true</option><option>false</option></select>
                        : (p.name === "sql" || p.name === "body" || p.name === "text" || p.name === "fact") ? <textarea className="input h-20 font-mono" value={vals[p.name] ?? ""} onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })} />
                          : <input className="input font-mono" value={vals[p.name] ?? ""} onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })} />}
                    {p.description && <p className="mt-0.5 text-[11px] text-mute">{p.description}</p>}</div>))}
                {formErr && <p className="text-sm text-bad">{formErr}</p>}
                <button className="btn btn-primary" disabled={run.isPending}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />}{run.isPending ? "Running…" : "Execute tool"}</button>
              </form>
              {run.error && <ErrorBox error={run.error} />}
              {run.data && <div><div className="mb-1 flex items-center gap-2"><Badge tone={run.data.ok ? "ok" : "bad"}>{run.data.ok ? "success" : run.data.status}</Badge><span className="text-xs text-mute">{ms(run.data.ms)}</span>{run.data.flags?.length > 0 && <Badge tone="warn">injection-scan: {run.data.flags.join(", ")}</Badge>}</div><Json value={run.data.output} max={360} /><p className="mt-1 text-[11px] text-mute">Output is redacted for secrets before it reaches your screen.</p></div>}
            </>)}
            {tab === "schema" && <><div className="space-y-0">{cur.params.map((p: any) => <KV key={p.name} k={`${p.name}${p.required ? " *" : ""}`} v={p.type} />)}</div><Json value={cur.schema} /></>}
            {tab === "history" && <div className="space-y-2"><KV k="Executions (this session)" v={cur.stats.count} /><KV k="Errors" v={cur.stats.errors} /><KV k="Last run" v={cur.stats.last_ts ? ago(cur.stats.last_ts) : UNAVAILABLE} /><KV k="Last latency" v={ms(cur.stats.last_ms)} />
              {(hist.data?.executions ?? []).filter((e: any) => e.tool === cur.name).slice(0, 10).map((e: any, i: number) => <div key={i} className="flex items-center justify-between rounded border border-line bg-bg/60 px-3 py-1.5 text-xs"><span>{e.source}</span><span className="text-mute">{ms(e.ms)}</span><Badge tone={e.ok ? "ok" : "bad"}>{e.ok ? "ok" : e.status}</Badge><span className="text-mute">{ago(e.ts)}</span></div>)}</div>}
          </div>}
        </Card>
      </div>
    </div>
  );
}
