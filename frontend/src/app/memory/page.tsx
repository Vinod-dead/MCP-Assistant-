"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";

export default function Memory() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["memory"], queryFn: () => api.get("/api/memory"), refetchInterval: 8000 });
  const [fact, setFact] = useState(""); const [tags, setTags] = useState(""); const [query, setQuery] = useState(""); const [applied, setApplied] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const search = useQuery({ queryKey: ["memory-search", applied], queryFn: () => api.get(`/api/memory/search?q=${encodeURIComponent(applied)}`), enabled: !!applied });
  const refresh = () => qc.invalidateQueries({ queryKey: ["memory"] });
  const add = useMutation({ mutationFn: () => api.post("/api/memory", { fact, tags }), onSuccess: (r) => { setNote({ ok: r.ok, text: r.ok ? "Saved." : r.output }); if (r.ok) { setFact(""); setTags(""); } refresh(); } });
  const del = useMutation({ mutationFn: (id: string) => api.del(`/api/memory/${id}`), onSuccess: (r) => { setNote({ ok: r.ok, text: r.ok ? "Deleted." : r.output }); refresh(); } });
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const records: any[] = q.data?.records ?? [];
  return (
    <div className="space-y-5">
      <PageHeader title="Memory Center" sub="Long-term facts the assistant remembers across chats. The most relevant ones are injected into the model prompt each turn; chat history is separate." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-4">
          <Card title="Test retrieval" right={<span className="text-xs text-mute">same keyword search the assistant uses</span>}>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(query.trim()); }}><div className="relative flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-mute" /><input className="input pl-9" placeholder="e.g. currency preference" value={query} onChange={(e) => setQuery(e.target.value)} /></div><button className="btn">Search</button></form>
            {applied && (search.isLoading ? <div className="mt-3"><Spinner /></div> : search.data && <div className="mt-3 space-y-2"><div className="text-xs text-mute">Query terms: {search.data.terms.map((t: string) => <span key={t} className="mr-1 rounded bg-bg px-1.5 py-0.5 font-mono">{t}</span>)}</div>
              {search.data.results.length === 0 ? <p className="text-sm text-mute">No memory matched — it would not be injected.</p> : search.data.results.map((r: any) => <div key={r.id} className="rounded-lg border border-accent/30 bg-accent/5 p-2 text-sm"><Badge tone="info">#{r.rank}</Badge> {r.fact}</div>)}</div>)}
          </Card>
          <Card title={`Stored memories (${records.length})`} pad={false} right={<span className="font-mono text-[11px] text-mute">{q.data?.file}</span>}>
            {q.isLoading ? <div className="p-4"><div className="sk h-24" /></div> : records.length === 0 ? <Empty icon={<Brain className="h-7 w-7" />} title="No memories yet" hint="Add one here, or tell the assistant “remember that …” in the AI Workspace." /> :
              <ul className="divide-y divide-line">{records.map((r) => (
                <li key={r.id} className="flex items-start gap-3 px-4 py-3"><div className="min-w-0 flex-1"><p className="text-sm">{r.fact}</p><div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-mute"><span className="font-mono">{r.id}</span>{r.created && <span>{ago(r.created)}</span>}{(r.tags ?? []).map((t: string) => <Badge key={t}>{t}</Badge>)}</div></div>
                  <button className="btn btn-danger h-8 px-2" aria-label="Delete memory" disabled={del.isPending} onClick={() => { if (confirm("Delete this memory? (policy may ask you to approve)")) del.mutate(r.id); }}><Trash2 className="h-3.5 w-3.5" /></button></li>))}</ul>}
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Add a memory">
            <div className="space-y-3"><textarea className="input h-24" maxLength={500} placeholder="e.g. Prefers amounts in INR lakhs" value={fact} onChange={(e) => setFact(e.target.value)} aria-label="Memory text" /><input className="input" placeholder="tags (comma separated, optional)" value={tags} onChange={(e) => setTags(e.target.value)} />
              <button className="btn btn-primary w-full" disabled={!fact.trim() || add.isPending} onClick={() => add.mutate()}>{add.isPending ? <Spinner /> : <Plus className="h-4 w-4" />}Save memory</button>
              {note && <p className={`text-xs ${note.ok ? "text-ok" : "text-bad"}`}>{note.text}</p>}{add.error && <ErrorBox error={add.error} />}</div>
          </Card>
          <Card title="What is supported"><ul className="space-y-1.5 text-xs text-mute"><li>✔ create, list, search, delete (through the real MCP memory tools)</li><li>✘ editing in place — delete and re-add instead</li><li>Deleting is a state-changing action, so the permission profile may ask you to approve it.</li></ul></Card>
        </div>
      </div>
    </div>
  );
}
