"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, statusTone } from "@/components/ui";
import { api } from "@/lib/api";
import { UNAVAILABLE, ago, ms } from "@/lib/format";

export default function Servers() {
  const qc = useQueryClient();
  const [probe, setProbe] = useState(false);
  const q = useQuery({ queryKey: ["servers", probe], queryFn: () => api.get(`/api/servers${probe ? "?probe=true" : ""}`), refetchInterval: probe ? false : 6000 });
  const restart = useMutation({ mutationFn: (n: string) => api.post(`/api/servers/${n}/restart`, {}), onSettled: () => qc.invalidateQueries({ queryKey: ["servers"] }) });
  const [sel, setSel] = useState<string | null>(null);
  const list = q.data?.servers ?? [];
  const cur = list.find((s: any) => s.name === sel);
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  return (
    <div className="space-y-5">
      <PageHeader title="Server Monitor" sub="Each card is a real MCP server process spoken to over stdio. Calls / errors / latency are counted by this Studio session."
        actions={<><button className="btn" onClick={() => { setProbe(true); setTimeout(() => qc.invalidateQueries({ queryKey: ["servers"] }), 0); }}><Activity className="h-4 w-4" />Ping all</button><button className="btn" onClick={() => q.refetch()}><RefreshCw className="h-4 w-4" />Refresh</button></>} />
      {restart.error && <ErrorBox error={restart.error} />}
      {restart.data && !restart.data.running && <ErrorBox error={`Restart of ${restart.data.name} failed: ${restart.data.error}`} />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {q.isLoading ? Array.from({ length: 6 }).map((_, i) => <div key={i} className="sk h-40" />) : list.length === 0 ? <Empty title="No servers configured" /> : list.map((s: any) => (
          <button key={s.name} onClick={() => setSel(s.name)} className={`card p-4 text-left transition hover:border-accent/50 ${sel === s.name ? "border-accent shadow-glow" : ""}`}>
            <div className="flex items-center justify-between"><span className="font-mono text-base font-semibold">{s.name}</span><Badge tone={statusTone(s.status)} dot>{s.status}</Badge></div>
            <div className="mt-1 truncate font-mono text-[11px] text-mute">{s.module}</div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center"><div><div className="text-lg font-semibold">{s.tools}</div><div className="label">tools</div></div><div><div className="text-lg font-semibold">{s.calls}</div><div className="label">calls</div></div><div><div className={`text-lg font-semibold ${s.errors ? "text-bad" : ""}`}>{s.errors}</div><div className="label">errors</div></div></div>
            <div className="mt-3 flex items-center justify-between text-[11px] text-mute"><span>avg {ms(s.avg_ms)}</span>{"responsive" in s && <Badge tone={s.responsive ? "ok" : "bad"}>{s.responsive ? `ping ${s.ping_ms} ms` : "no ping reply"}</Badge>}</div>
            {s.startup_error && <div className="mt-2 break-words rounded border border-bad/30 bg-bad/5 p-2 text-[11px] text-bad">{s.startup_error}</div>}
          </button>))}
      </div>
      {cur && (
        <Card title={`${cur.name} — details`} right={<button className="btn btn-danger" disabled={restart.isPending} onClick={() => restart.mutate(cur.name)}>{restart.isPending ? <Spinner /> : <RotateCcw className="h-4 w-4" />}Restart server</button>}>
          <div className="grid gap-4 md:grid-cols-2">
            <div><div className="label mb-2">Tools ({cur.tool_names.length})</div><div className="flex flex-wrap gap-1.5">{cur.tool_names.map((t: string) => <span key={t} className="rounded bg-bg px-2 py-1 font-mono text-xs text-accent">{t}</span>)}{cur.tool_names.length === 0 && <span className="text-sm text-mute">none registered</span>}</div></div>
            <div className="space-y-1 text-sm"><div className="flex justify-between"><span className="text-mute">Last success</span><span>{cur.last_ok_ts ? ago(cur.last_ok_ts) : UNAVAILABLE}</span></div><div className="flex justify-between"><span className="text-mute">Last error</span><span>{cur.last_error ? `${ago(cur.last_error_ts)}` : "none"}</span></div>{cur.last_error && <p className="break-words rounded border border-bad/30 bg-bad/5 p-2 text-xs text-bad">{cur.last_error}</p>}
              <p className="pt-2 text-[11px] text-mute">Restart stops and relaunches this server’s process; it waits for any running chat request to finish first.</p></div>
          </div>
        </Card>)}
    </div>
  );
}
