"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { Badge, Card, ErrorBox, KV, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

export default function Settings() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api.get("/api/settings") });
  const sw = useMutation({ mutationFn: (profile: string) => api.post("/api/settings/profile", { profile }), onSettled: () => qc.invalidateQueries() });
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Settings" sub="Configuration lives in the server’s .env and config/*.yaml. Secret values are never sent to the browser — only whether each one is set." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Permission profile" right={s && <Badge tone="violet">active: {s.profile}</Badge>}>
          {!s ? <div className="sk h-40" /> : <div className="space-y-2">{s.profiles.map((p: any) => {
            const can = s.can_switch_to.includes(p.name), active = p.name === s.profile;
            return <div key={p.name} className={`flex items-center justify-between gap-3 rounded-lg border p-3 ${active ? "border-accent/50 bg-accent/5" : "border-line"}`}><div className="min-w-0"><div className="text-sm font-medium">{p.name}</div><div className="text-xs text-mute">{p.description}</div><div className="mt-1 flex gap-1.5 text-[10.5px] text-mute">read: {p.read_only} · write: {p.state_changing} · destructive: {p.destructive}</div></div>
              {active ? <Badge tone="ok">active</Badge> : <button className="btn" disabled={!can || sw.isPending} title={can ? "" : `Started with '${s.startup_profile}'. Restart with --profile ${p.name} to raise privileges.`} onClick={() => sw.mutate(p.name)}>{sw.isPending ? <Spinner /> : "Switch"}</button>}</div>;
          })}<p className="text-xs text-mute">Started with <span className="font-mono">{s.startup_profile}</span>. Privileges can be lowered here; raising them requires a restart with <span className="font-mono">--profile</span>, so the browser can never escalate itself.</p>{sw.error && <ErrorBox error={sw.error} />}</div>}
        </Card>
        <Card title="Environment (set / not set)">{!s ? <div className="sk h-40" /> : <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">{Object.entries(s.environment).map(([k, v]) => <div key={k} className="flex items-center justify-between border-b border-line/50 py-1.5 text-sm"><span className="font-mono text-xs">{k}</span>{v ? <Check className="h-4 w-4 text-ok" aria-label="set" /> : <X className="h-4 w-4 text-mute" aria-label="not set" />}</div>)}</div>}</Card>
        <Card title="Runtime">{!s ? <div className="sk h-24" /> : <><KV k="Version" v={s.runtime.version} /><KV k="Provider" v={s.runtime.provider} /><KV k="Model" v={s.runtime.model} /><KV k="Python" v={s.runtime.python} /><KV k="Platform" v={s.runtime.platform} /><KV k="Reflection pass" v={s.reflect ? "on" : "off"} /></>}</Card>
        <Card title="Paths">{!s ? <div className="sk h-24" /> : <>{Object.entries(s.paths).map(([k, v]) => <KV key={k} k={k.replace("_", " ")} v={String(v)} />)}</>}</Card>
      </div>
    </div>
  );
}
