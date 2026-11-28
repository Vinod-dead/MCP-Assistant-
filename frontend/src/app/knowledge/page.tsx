"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, RefreshCw, Search } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, KV, PageHeader, Spinner, Table, statusTone } from "@/components/ui";
import { api } from "@/lib/api";
import { UNAVAILABLE, ago, num } from "@/lib/format";

export default function Knowledge() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["knowledge"], queryFn: () => api.get("/api/knowledge"), refetchInterval: 10000 });
  const [query, setQuery] = useState("");
  const index = useMutation({ mutationFn: () => api.post("/api/knowledge/index", { path: "." }), onSettled: () => qc.invalidateQueries({ queryKey: ["knowledge"] }) });
  const search = useMutation({ mutationFn: () => api.post("/api/knowledge/search", { query, k: 5 }) });
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data; const s = search.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Knowledge Base" sub="Documents the assistant can retrieve from. Retrieval is a transparent keyword (BM25) search, plus Gemini embeddings when configured."
        actions={<button className="btn btn-primary" disabled={index.isPending} onClick={() => index.mutate()}>{index.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}Index workspace</button>} />
      {index.data && <div className={`rounded-lg border p-3 text-sm ${index.data.ok ? "border-ok/30 bg-ok/5" : "border-bad/30 bg-bad/5"}`}>{index.data.output}</div>}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <Card title="Search & retrieval trace">
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (query.trim()) search.mutate(); }}><div className="relative flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-mute" /><input className="input pl-9" placeholder="e.g. refund policy" value={query} onChange={(e) => setQuery(e.target.value)} /></div><button className="btn btn-primary" disabled={search.isPending}>{search.isPending ? <Spinner /> : "Search"}</button></form>
            {search.error && <div className="mt-3"><ErrorBox error={search.error} /></div>}
            {s && <div className="mt-4 space-y-3">
              <div className="flex flex-wrap gap-2 text-xs"><Badge>mode: {s.steps.mode}</Badge><Badge>{num(s.steps.chunks_searched)} chunks · {s.steps.documents} docs</Badge><Badge>terms: {s.steps.query_terms.join(", ") || UNAVAILABLE}</Badge></div>
              {s.index_empty ? <Empty title="The index is empty" hint="Click “Index workspace” first." /> : s.results.length === 0 ? <Empty title="No relevant chunks found" /> : s.results.map((r: any, i: number) => (
                <div key={i} className="rounded-lg border border-line bg-bg/60 p-3"><div className="mb-1 flex items-center justify-between text-xs"><span className="flex items-center gap-1.5 font-mono text-accent"><FileText className="h-3 w-3" />{r.source}</span><span className="flex items-center gap-2 text-mute">{r.score !== undefined && <span>score {Number(r.score).toFixed(3)}</span>}<Badge tone="info">{r.mode}</Badge></span></div>
                  <p className="whitespace-pre-wrap text-sm">{r.text}</p>{r.matched_terms?.length > 0 && <div className="mt-2 text-[11px] text-mute">matched: {r.matched_terms.map((t: string) => <span key={t} className="mr-1 rounded bg-accent/10 px-1 text-accent">{t}</span>)}</div>}</div>))}</div>}
          </Card>
          <Card title="Documents" pad={false}>
            {!d ? <div className="p-4"><div className="sk h-24" /></div> : d.documents.length === 0 ? <Empty title="No supported documents found" hint={`Add .md, .txt, .pdf, .docx or .csv files under ${d.root}.`} /> : <Table head={["Document", "Status", "Chunks", "Vectors", "Indexed"]}>{d.documents.map((x: any) => <tr key={x.source}><td className="td">{x.source}</td><td className="td"><Badge tone={statusTone(x.status === "indexed" ? "ok" : "warn")}>{x.status}</Badge></td><td className="td">{x.chunks}</td><td className="td">{x.vectors}</td><td className="td">{x.indexed_at ? ago(x.indexed_at) : UNAVAILABLE}</td></tr>)}</Table>}
          </Card>
        </div>
        <Card title="Index">{!d ? <div className="sk h-32" /> : <><KV k="Documents" v={d.documents.filter((x: any) => x.chunks > 0).length} /><KV k="Chunks" v={d.chunks} /><KV k="With embeddings" v={d.with_embeddings} /><p className="mt-3 text-xs text-mute">{d.mode}</p><p className="mt-2 break-all text-[11px] text-mute">Source folder: {d.root}</p></>}</Card>
      </div>
    </div>
  );
}
