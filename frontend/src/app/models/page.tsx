"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Play, PlugZap } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, KV, PageHeader, Spinner, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { UNAVAILABLE, ago, compact, ms, num, pct, usd } from "@/lib/format";

export default function ModelLab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["model"], queryFn: () => api.get("/api/model"), refetchInterval: 8000 });
  const [system, setSystem] = useState("You are a concise assistant.");
  const [prompt, setPrompt] = useState("Explain what the Model Context Protocol is in two sentences.");
  const [temp, setTemp] = useState(0.2);
  const test = useMutation({ mutationFn: () => api.post("/api/model/test", {}), onSettled: () => qc.invalidateQueries({ queryKey: ["model"] }) });
  const play = useMutation({ mutationFn: () => api.post("/api/model/playground", { system, prompt, temperature: temp }), onSettled: () => qc.invalidateQueries({ queryKey: ["model"] }) });
  const m = q.data;
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const conn = m?.connection === "ok" ? "ok" : m?.connection === "error" ? "bad" : "mute";
  return (
    <div className="space-y-5">
      <PageHeader title="Model Lab" sub="The configured model, measured from real requests. Context-window size and benchmarks are intentionally not shown: this app has no verified source for them."
        actions={<button className="btn" disabled={test.isPending} onClick={() => test.mutate()}>{test.isPending ? <Spinner /> : <PlugZap className="h-4 w-4" />}Test connection</button>} />
      {test.data && <div className={`rounded-lg border p-3 text-sm ${test.data.ok ? "border-ok/30 bg-ok/5" : "border-bad/30 bg-bad/5"}`}>{test.data.ok ? `Connection OK — replied in ${ms(test.data.latency_ms)}.` : `Connection failed: ${test.data.error}`}</div>}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Active model" className="lg:col-span-1" right={m && <Badge tone={conn as any} dot>{m.connection === "not_tested" ? "not tested" : m.connection}</Badge>}>
          {!m ? <div className="sk h-40" /> : <div>
            <div className="mb-3 flex items-center gap-2"><Cpu className="h-5 w-5 text-violet" /><span className="break-all font-mono text-sm">{m.model}</span></div>
            <KV k="Provider" v={m.provider} /><KV k="Endpoint" v={m.endpoint ?? UNAVAILABLE} /><KV k="Credentials" v={m.credentials_configured ? "configured (server-side)" : "missing"} />
            <KV k="Temperature" v={m.temperature ?? UNAVAILABLE} /><KV k="Timeout" v={m.timeout_s ? `${m.timeout_s}s` : UNAVAILABLE} /><KV k="Token streaming" v={m.streaming_supported ? "yes" : "no"} />
            {m.offline_demo && <p className="mt-3 rounded-md border border-warn/30 bg-warn/5 p-2 text-xs text-warn">Offline demo: this is the keyword-matching mock, not a real model.</p>}
            <p className="mt-3 text-[11px] text-mute">API keys never reach the browser; only “configured / missing” is shown.</p>
          </div>}
        </Card>
        <div className="grid grid-cols-2 gap-3 lg:col-span-2">
          <Stat label="Requests" value={num(m?.usage.requests)} sub={m && `${m.usage.successes} succeeded`} loading={!m} />
          <Stat label="Success rate" value={pct(m?.usage.success_rate)} loading={!m} />
          <Stat label="Avg latency" value={ms(m?.usage.avg_latency_ms)} loading={!m} sub="per LLM call" />
          <Stat label="Tokens in / out" value={m ? `${compact(m.usage.input_tokens)} / ${compact(m.usage.output_tokens)}` : "…"} loading={!m} />
          <Stat label="Est. cost" value={usd(m?.usage.est_cost_usd)} loading={!m} sub={m && `$${m.pricing_per_million.input}/M in · $${m.pricing_per_million.output}/M out`} />
          <Stat label="Last call" value={m?.last_call ? ago(m.last_call.ts) : UNAVAILABLE} loading={!m} sub={m?.last_call && (m.last_call.ok ? "succeeded" : "failed")} />
        </div>
      </div>
      {m && <p className="text-[11px] text-mute">{m.pricing_per_million.note}</p>}

      <Card title="Playground" right={<span className="text-xs text-mute">single prompt · no tools · no history</span>}>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <div><div className="label mb-1">System prompt</div><textarea className="input h-20" value={system} onChange={(e) => setSystem(e.target.value)} /></div>
            <div><div className="label mb-1">Prompt</div><textarea className="input h-32" value={prompt} onChange={(e) => setPrompt(e.target.value)} /></div>
            <div className="flex items-center gap-3"><div className="label">Temperature {temp.toFixed(1)}</div><input type="range" min={0} max={1.5} step={0.1} value={temp} onChange={(e) => setTemp(+e.target.value)} className="flex-1 accent-[#5b8cff]" aria-label="Temperature" />
              <button className="btn btn-primary" disabled={play.isPending || !prompt.trim()} onClick={() => play.mutate()}>{play.isPending ? <Spinner /> : <Play className="h-4 w-4" />}Run</button></div>
          </div>
          <div className="min-h-[220px] rounded-lg border border-line bg-bg p-3">
            {play.isPending ? <div className="flex items-center gap-2 text-sm text-mute"><Spinner />Waiting for the model…</div> : play.error ? <ErrorBox error={play.error} /> : play.data ? (play.data.ok ? <>
              <p className="whitespace-pre-wrap text-sm">{play.data.text}</p>
              <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-2 text-[11px] text-mute"><Badge>{ms(play.data.latency_ms)}</Badge><Badge>{play.data.input_tokens} in / {play.data.output_tokens} out</Badge><Badge>{play.data.tokens_per_sec ? `${play.data.tokens_per_sec} tok/s` : "tok/s Unavailable"}</Badge><Badge>{usd(play.data.est_cost_usd)}</Badge></div></> :
              <ErrorBox error={play.data.error} />) : <Empty title="Run a prompt to see the response and its real latency" />}
          </div>
        </div>
      </Card>

      <Card title="Recent model calls" pad={false}>
        {!m ? <div className="p-4"><div className="sk h-24" /></div> : m.recent_calls.length === 0 ? <Empty title="No model calls yet" /> : <Table head={["When", "Result", "Latency", "In", "Out", "Tool calls", "Error"]}>
          {m.recent_calls.map((c: any, i: number) => <tr key={i}><td className="td">{ago(c.ts)}</td><td className="td"><Badge tone={c.ok ? "ok" : "bad"}>{c.ok ? "ok" : "error"}</Badge></td><td className="td">{ms(c.ms)}</td><td className="td">{c.input_tokens}</td><td className="td">{c.output_tokens}</td><td className="td">{c.tool_calls ?? 0}</td><td className="td max-w-[320px] truncate text-bad">{c.error ?? ""}</td></tr>)}</Table>}
      </Card>
    </div>
  );
}
