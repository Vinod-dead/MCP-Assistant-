"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Database, Lock, Play, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { SqlView } from "@/components/sqlview";
import { Badge, Card, Empty, ErrorBox, KV, PageHeader, Spinner, Table, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { UNAVAILABLE, ago, ms, num } from "@/lib/format";
import { looksLikeWrite } from "@/lib/sql";

type Tab = "browse" | "sql" | "schema" | "relations" | "history";

function ResultGrid({ r }: { r: { columns: string[]; rows: any[][] } }) {
  if (!r.columns.length) return null;
  return <Table head={r.columns} empty={r.rows.length === 0}>{r.rows.map((row, i) => <tr key={i} className="hover:bg-panel2/60">{row.map((c, j) => <td key={j} className="td max-w-[320px] truncate" title={c === null ? "NULL" : String(c)}>{c === null ? <span className="italic text-mute">NULL</span> : String(c)}</td>)}</tr>)}</Table>;
}

export default function DatabasePage() {
  const ov = useQuery({ queryKey: ["db-overview"], queryFn: () => api.get("/api/database/overview"), refetchInterval: 15000 });
  const tbl = useQuery({ queryKey: ["db-tables"], queryFn: () => api.get("/api/database/tables") });
  const [tab, setTab] = useState<Tab>("browse"); const [table, setTable] = useState<string | null>(null);
  useEffect(() => { if (!table && tbl.data?.tables?.length) setTable(tbl.data.tables[0].name); }, [tbl.data, table]);
  const o = ov.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Database Explorer" sub="Read-only by design: the explorer uses the same read-only connection and SQL guard as the assistant’s db tools."
        actions={<Badge tone="ok" dot><Lock className="mr-1 inline h-3 w-3" />read-only</Badge>} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[["Connection", o ? <Badge tone={o.connection === "connected" ? "ok" : "bad"} dot>{o.connection}</Badge> : "…"], ["Engine", o?.dialect ?? "…"], ["Database", o?.database || UNAVAILABLE], ["Tables", num(o?.table_count)], ["Total rows", num(o?.total_rows)]].map(([k, v], i) => (
          <div key={i} className="card p-3"><div className="label">{k}</div><div className="mt-1 truncate text-lg font-semibold">{v as any}</div></div>))}
      </div>
      {o?.error && <ErrorBox error={o.error} />}
      <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <Card title="Tables" pad={false}>
          {tbl.isLoading ? <div className="p-3"><div className="sk h-24" /></div> : tbl.isError ? <div className="p-3"><ErrorBox error={tbl.error} /></div> : tbl.data.tables.length === 0 ? <Empty title="No tables" /> :
            <ul className="p-1.5">{tbl.data.tables.map((t: any) => <li key={t.name}><button onClick={() => { setTable(t.name); if (tab === "sql" || tab === "history" || tab === "relations") setTab("browse"); }} className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-sm transition hover:bg-panel2 ${t.name === table ? "bg-accent/10 ring-1 ring-accent/30" : ""}`}><span className="flex items-center gap-2 font-mono"><Database className="h-3.5 w-3.5 text-mute" />{t.name}</span><span className="text-xs text-mute">{num(t.rows)}</span></button></li>)}</ul>}
        </Card>
        <div className="min-w-0 space-y-4">
          <Tabs value={tab} onChange={setTab} items={[{ id: "browse", label: "Data" }, { id: "sql", label: "SQL" }, { id: "schema", label: "Schema" }, { id: "relations", label: "Relationships" }, { id: "history", label: "History" }]} />
          {tab === "browse" && table && <Browse table={table} />}
          {tab === "sql" && <SqlWorkspace />}
          {tab === "schema" && table && <Schema table={table} />}
          {tab === "relations" && <Relations />}
          {tab === "history" && <History />}
        </div>
      </div>
    </div>
  );
}

function Browse({ table }: { table: string }) {
  const [page, setPage] = useState(1); const [sort, setSort] = useState<string | null>(null); const [order, setOrder] = useState<"asc" | "desc">("asc"); const [search, setSearch] = useState(""); const [applied, setApplied] = useState("");
  useEffect(() => { setPage(1); setSort(null); setSearch(""); setApplied(""); }, [table]);
  const q = useQuery({ queryKey: ["db-browse", table, page, sort, order, applied], queryFn: () => api.post("/api/database/browse", { table, page, page_size: 25, sort, order, search: applied }), placeholderData: (p) => p });
  const d = q.data;
  return (
    <Card pad={false} title={<span className="font-mono">{table}</span>} right={<form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(search); setPage(1); }}><input className="input w-48" placeholder="Search rows…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search rows" /><button className="btn">Search</button></form>}>
      {q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : !d ? <div className="p-4"><div className="sk h-48" /></div> : <>
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full border-collapse"><thead><tr>{d.columns.map((c: string) => <th key={c} className="th cursor-pointer select-none hover:text-ink" onClick={() => { if (sort === c) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(c); setOrder("asc"); } }}>{c}{sort === c ? (order === "asc" ? " ▲" : " ▼") : ""}{d.masked_columns.includes(c) && " 🔒"}</th>)}</tr></thead>
            <tbody className="divide-y divide-line/70">{d.rows.map((row: any[], i: number) => <tr key={i} className="hover:bg-panel2/60">{row.map((c, j) => <td key={j} className="td max-w-[300px] truncate" title={c === null ? "NULL" : String(c)}>{c === null ? <span className="italic text-mute">NULL</span> : String(c)}</td>)}</tr>)}</tbody></table>
          {d.rows.length === 0 && <Empty title="No rows match" />}
        </div>
        <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-mute">
          <span>{num(d.total)} rows · {ms(d.ms)}{d.masked_columns.length > 0 && ` · 🔒 ${d.masked_columns.join(", ")} masked`}</span>
          <span className="flex items-center gap-2"><button className="btn h-7 px-2" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-3.5 w-3.5" /></button>page {d.page} / {d.pages}<button className="btn h-7 px-2" disabled={page >= d.pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="h-3.5 w-3.5" /></button></span>
        </div></>}
    </Card>
  );
}

function SqlWorkspace() {
  const [sql, setSql] = useState("SELECT c.name, COUNT(*) AS invoices, ROUND(SUM(i.amount), 2) AS total\nFROM invoices i JOIN customers c ON c.id = i.customer_id\nGROUP BY c.name\nORDER BY total DESC\nLIMIT 10");
  const run = useMutation({ mutationFn: () => api.post("/api/database/query", { sql, max_rows: 200 }) });
  const write = looksLikeWrite(sql);
  const r = run.data;
  return (
    <div className="space-y-3">
      <Card title="SQL workspace" right={<Badge tone="ok" dot>read-only · SELECT / WITH / EXPLAIN</Badge>}>
        <div className="relative"><textarea className="input h-36 resize-y font-mono text-[12.5px] leading-relaxed" spellCheck={false} value={sql} onChange={(e) => setSql(e.target.value)} aria-label="SQL" onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run.mutate(); }} /></div>
        {sql.trim() && <div className="mt-2 rounded-lg border border-line bg-bg p-2"><SqlView sql={sql} /></div>}
        {write && <div className="mt-3 flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/5 p-3 text-sm text-warn"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" /><span>This looks like a <b>write</b>. The explorer will reject it. Writes exist only as the <span className="font-mono">db__execute_write</span> MCP tool, which requires your approval (or is blocked in the read-only profile).</span></div>}
        <div className="mt-3 flex items-center gap-3"><button className="btn btn-primary" disabled={run.isPending || !sql.trim()} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />}Run query</button><span className="text-xs text-mute">Ctrl+Enter · 10 s limit · max 1000 rows</span></div>
      </Card>
      {run.error && <ErrorBox error={run.error} />}
      {r && (r.ok ? <Card pad={false} title="Result" right={<span className="text-xs text-mute">{r.row_count} rows{r.truncated ? " (truncated)" : ""} · {ms(r.ms)}</span>}><ResultGrid r={r} />{r.masked_columns.length > 0 && <div className="border-t border-line px-4 py-2 text-xs text-mute">🔒 masked: {r.masked_columns.join(", ")}</div>}</Card> : <ErrorBox error={r.error} />)}
    </div>
  );
}

function Schema({ table }: { table: string }) {
  const q = useQuery({ queryKey: ["db-schema", table], queryFn: () => api.get(`/api/database/schema/${encodeURIComponent(table)}`) });
  if (q.isError) return <ErrorBox error={q.error} />;
  const s = q.data;
  return !s ? <div className="sk h-48" /> : (
    <Card title={<span className="font-mono">{s.name}</span>} right={<Badge>{num(s.rows)} rows</Badge>} pad={false}>
      <Table head={["Column", "Type", "Null", "Key", "Default", "References"]}>{s.columns.map((c: any) => (
        <tr key={c.name}><td className="td">{c.name}{c.sensitive && <Badge tone="warn">masked</Badge>}</td><td className="td text-violet">{c.type}</td><td className="td">{c.nullable ? "yes" : "no"}</td><td className="td">{c.primary_key && <Badge tone="info">PK</Badge>} {c.unique && <Badge>unique</Badge>}</td><td className="td text-mute">{c.default ?? ""}</td><td className="td">{c.foreign_key ? `${c.foreign_key.table}.${c.foreign_key.column}` : ""}</td></tr>))}</Table>
      <div className="grid gap-4 p-4 md:grid-cols-2"><div><div className="label mb-1">Indexes</div>{s.indexes.length ? s.indexes.map((i: any, k: number) => <KV key={k} k={i.name ?? "(unnamed)"} v={`${i.columns.join(", ")}${i.unique ? " · unique" : ""}`} />) : <p className="text-sm text-mute">None</p>}</div>
        <div><div className="label mb-1">Referenced by</div>{s.referenced_by.length ? s.referenced_by.map((r: any, k: number) => <KV key={k} k={r.table} v={r.columns.join(", ")} />) : <p className="text-sm text-mute">Nothing</p>}</div></div>
    </Card>
  );
}

function Relations() {
  const q = useQuery({ queryKey: ["db-rel"], queryFn: () => api.get("/api/database/relations") });
  if (q.isError) return <ErrorBox error={q.error} />;
  if (!q.data) return <div className="sk h-48" />;
  const { nodes, edges } = q.data;
  if (!nodes.length) return <Empty title="No tables" />;
  const W = 210, rowH = 17, gap = 60;
  const pos: Record<string, { x: number; y: number; h: number }> = {};
  nodes.forEach((n: any, i: number) => { const h = 30 + n.columns.length * rowH; pos[n.id] = { x: 20 + (i % 3) * (W + gap), y: 20 + Math.floor(i / 3) * 230, h }; });
  const H = 40 + (Math.floor((nodes.length - 1) / 3) + 1) * 230, Wd = 40 + Math.min(nodes.length, 3) * (W + gap);
  return (
    <Card title="Entity relationships" right={<span className="text-xs text-mute">read from the live schema</span>}>
      <div className="overflow-auto"><svg width={Wd} height={H} role="img" aria-label="Entity relationship diagram">
        <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#5b8cff" /></marker></defs>
        {edges.map((e: any, i: number) => { const a = pos[e.from], b = pos[e.to]; if (!a || !b) return null; const x1 = a.x + (b.x >= a.x ? W : 0), x2 = b.x + (b.x >= a.x ? 0 : W); return <g key={i}><path d={`M${x1},${a.y + 15} C${(x1 + x2) / 2},${a.y + 15} ${(x1 + x2) / 2},${b.y + 15} ${x2},${b.y + 15}`} stroke="#5b8cff" strokeWidth="1.5" fill="none" markerEnd="url(#ar)" /><text x={(x1 + x2) / 2} y={(a.y + b.y) / 2 + 12} fill="#8a93a8" fontSize="10" textAnchor="middle">{e.columns.join(",")}→{e.ref_columns.join(",")}</text></g>; })}
        {nodes.map((n: any) => { const p = pos[n.id]; return <g key={n.id}><rect x={p.x} y={p.y} width={W} height={p.h} rx="8" fill="#151a26" stroke="#2a3247" /><rect x={p.x} y={p.y} width={W} height="28" rx="8" fill="#5b8cff22" /><text x={p.x + 10} y={p.y + 19} fill="#e7eaf3" fontSize="13" fontWeight="600" fontFamily="monospace">{n.id}</text>
          {n.columns.map((c: any, i: number) => <text key={c.name} x={p.x + 10} y={p.y + 44 + i * rowH} fontSize="11" fontFamily="monospace" fill={c.pk ? "#fbbf24" : c.fk ? "#5b8cff" : "#aab2c5"}>{c.pk ? "🔑 " : c.fk ? "↗ " : "   "}{c.name} <tspan fill="#5d667c">{String(c.type).toLowerCase()}</tspan></text>)}</g>; })}
      </svg></div>
    </Card>
  );
}

function History() {
  const q = useQuery({ queryKey: ["db-history"], queryFn: () => api.get("/api/database/history"), refetchInterval: 5000 });
  const h = q.data?.history ?? [];
  return <Card title="Explorer query history" pad={false}>{q.isLoading ? <div className="p-4"><div className="sk h-24" /></div> : h.length === 0 ? <Empty title="No queries yet" hint="Queries you run in the SQL tab are listed here." /> : <ul className="divide-y divide-line">{h.map((x: any, i: number) => <li key={i} className="px-4 py-2"><SqlView sql={x.sql} /><div className="mt-1 flex gap-3 text-[11px] text-mute"><Badge tone={x.ok ? "ok" : "bad"}>{x.ok ? `${x.rows} rows` : "failed"}</Badge>{ms(x.ms)} · {ago(x.ts)}{x.error && <span className="truncate text-bad">{x.error}</span>}</div></li>)}</ul>}</Card>;
}
