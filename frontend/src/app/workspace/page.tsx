"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown, Copy, MessageSquarePlus, RefreshCw, Search, Send, Square, Trash2, Wrench, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Markdown } from "@/components/markdown";
import { Badge, Card, Empty, ErrorBox, Json, Spinner, cx } from "@/components/ui";
import { Stage, Workflow, stageFor } from "@/components/workflow";
import { ApiError, api, streamPost } from "@/lib/api";
import { EXAMPLES } from "@/lib/examples";
import { ago, ms, num, short } from "@/lib/format";

type Msg = { id: string; role: "user" | "assistant"; content: string; status?: string; steps?: any[]; metrics?: any; error?: string | null; ts?: string };

function Steps({ steps }: { steps: any[] }) {
  const calls = steps.filter((s) => ["tool_call", "tool_result", "tool_blocked", "approval"].includes(s.type));
  if (!calls.length) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {calls.map((s, i) => <StepRow key={i} s={s} />)}
    </div>
  );
}
function StepRow({ s }: { s: any }) {
  const [open, setOpen] = useState(false);
  const tone = s.type === "tool_blocked" ? "bad" : s.type === "approval" ? "warn" : s.type === "tool_result" ? (s.ok ? "ok" : "bad") : "info";
  const label = s.type === "tool_call" ? "calling" : s.type === "tool_result" ? (s.ok ? "result" : "failed") : s.type === "tool_blocked" ? `blocked (${s.status})` : "needs approval";
  const body = s.type === "tool_result" ? s.output : s.type === "tool_call" || s.type === "tool_blocked" || s.type === "approval" ? s.args : undefined;
  return (
    <div className="rounded-lg border border-line bg-bg/60">
      <button className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs" onClick={() => setOpen(!open)}>
        <Wrench className="h-3 w-3 text-mute" /><span className="font-mono text-accent">{s.name ?? s.tool}</span><Badge tone={tone as any}>{label}</Badge>
        {s.ms != null && <span className="text-mute">{ms(s.ms)}</span>}{s.flags?.length > 0 && <Badge tone="warn">injection-scan: {s.flags.length}</Badge>}
        <ChevronDown className={cx("ml-auto h-3 w-3 text-mute transition", open && "rotate-180")} />
      </button>
      {open && body !== undefined && <div className="border-t border-line p-2"><Json value={body} max={220} /></div>}
    </div>
  );
}

function Bubble({ m, onCopy, last, onRegen, busy }: { m: Msg; onCopy: (t: string) => void; last: boolean; onRegen: () => void; busy: boolean }) {
  const user = m.role === "user";
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cx("flex", user ? "justify-end" : "justify-start")}>
      <div className={cx("max-w-[88%] rounded-2xl px-4 py-3 text-sm", user ? "bg-accent/15 ring-1 ring-accent/30" : "card")}>
        {user ? <p className="whitespace-pre-wrap">{m.content}</p> : <>
          {m.status === "error" && <div className="mb-2 text-bad">⚠ This request failed.</div>}
          <Markdown>{m.content || "…"}</Markdown>
          <Steps steps={m.steps ?? []} />
          <div className="mt-3 flex items-center gap-3 border-t border-line pt-2 text-[11px] text-mute">
            <span>{m.metrics?.summary ?? ""}</span>
            <button className="ml-auto flex items-center gap-1 hover:text-ink" onClick={() => onCopy(m.content)}><Copy className="h-3 w-3" />Copy</button>
            {last && <button className="flex items-center gap-1 hover:text-ink disabled:opacity-40" disabled={busy} onClick={onRegen}><RefreshCw className="h-3 w-3" />Regenerate</button>}
          </div></>}
      </div>
    </motion.div>
  );
}

export default function Workspace() {
  const qc = useQueryClient();
  const [convId, setConvId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<{ text: string; events: any[] }>({ text: "", events: [] });
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Stage>("idle");

  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get("/api/health"), refetchInterval: 5000 });
  const convs = useQuery({ queryKey: ["convs", search], queryFn: () => api.get(`/api/conversations?q=${encodeURIComponent(search)}`), refetchInterval: running ? false : 8000 });
  const ctx = useQuery({ queryKey: ["ctx", convId, msgs.length], queryFn: () => api.get(`/api/conversations/${convId}/context`), enabled: !!convId && !running });
  const mem = useQuery({ queryKey: ["memory"], queryFn: () => api.get("/api/memory"), enabled: true });

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, live.text, live.events.length]);

  const open = useCallback(async (id: string) => {
    try { const c = await api.get(`/api/conversations/${id}`); setConvId(id); setMsgs(c.messages); setError(null); setStage("idle"); setLive({ text: "", events: [] }); }
    catch (e: any) { setError(e.message); }
  }, []);

  const run = useCallback(async (path: string, body: unknown, optimistic?: Msg) => {
    setRunning(true); setError(null); setLive({ text: "", events: [] }); stageRef.current = "idle"; setStage("idle");
    if (optimistic) setMsgs((m) => [...m, optimistic]);
    const ac = new AbortController(); abort.current = ac;
    try {
      await streamPost(path, body, ({ data: ev }) => {
        const next = stageFor(ev, stageRef.current); stageRef.current = next; setStage(next);
        if (ev.type === "start") { setConvId(ev.conversation_id); if (ev.regenerated) setMsgs((m) => m.filter((x, i) => !(i === m.length - 1 && x.role === "assistant"))); }
        else if (ev.type === "token") setLive((l) => ({ ...l, text: l.text + ev.text }));
        else if (ev.type === "llm_start") setLive((l) => ({ text: "", events: [...l.events, ev] }));
        else if (["tool_call", "tool_result", "tool_blocked", "approval", "llm_call", "reflection"].includes(ev.type)) setLive((l) => ({ ...l, events: [...l.events, ev] }));
        else if (ev.type === "done" || ev.type === "stopped") setMsgs((m) => [...m, ev.message]);
        else if (ev.type === "error") setError(ev.message);
      }, ac.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e instanceof ApiError ? e.message : "Connection lost while streaming.");
    } finally {
      setRunning(false); abort.current = null; setLive({ text: "", events: [] });
      qc.invalidateQueries({ queryKey: ["convs"] }); qc.invalidateQueries({ queryKey: ["memory"] }); qc.invalidateQueries({ queryKey: ["overview"] });
    }
  }, [qc]);

  const send = useCallback((text: string) => {
    const t = text.trim(); if (!t || running) return;
    setInput("");
    run("/api/chat", { message: t, conversation_id: convId }, { id: `u${Date.now()}`, role: "user", content: t });
  }, [run, convId, running]);

  const stop = async () => { try { await api.post("/api/chat/stop", {}); } catch { /* ignore */ } abort.current?.abort(); };
  const newChat = () => { if (running) return; setConvId(null); setMsgs([]); setStage("idle"); setError(null); };

  // deep link: /workspace/?prompt=... sends once
  const prompted = useRef(false);
  useEffect(() => {
    if (prompted.current) return; prompted.current = true;
    const p = new URLSearchParams(window.location.search).get("prompt");
    if (p) { window.history.replaceState(null, "", window.location.pathname); setTimeout(() => send(p), 100); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const calls = live.events.filter((e) => e.type === "tool_call" || e.type === "tool_result" || e.type === "tool_blocked" || e.type === "approval");
  const lastCall = [...msgs].reverse().find((m) => m.role === "assistant")?.metrics;
  const model = health.data?.model;

  return (
    <div className="grid h-[calc(100vh-7.5rem)] min-h-[560px] gap-4 lg:grid-cols-[250px_minmax(0,1fr)] xl:grid-cols-[250px_minmax(0,1fr)_300px]">
      {/* conversations */}
      <Card className="hidden min-h-0 flex-col lg:flex" pad={false} title="Conversations" right={<button className="btn h-7 px-2" onClick={newChat} aria-label="New conversation"><MessageSquarePlus className="h-3.5 w-3.5" /></button>}>
        <div className="p-2"><div className="relative"><Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-mute" /><input className="input pl-8" placeholder="Search history" value={search} onChange={(e) => setSearch(e.target.value)} /></div></div>
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2 pt-0">
          {convs.isLoading ? <div className="sk h-16" /> : convs.data?.conversations.length === 0 ? <div className="p-3 text-xs text-mute">No conversations yet.</div> :
            convs.data?.conversations.map((c: any) => (
              <div key={c.id} className={cx("group flex items-start gap-1 rounded-lg px-2.5 py-2 text-sm transition", c.id === convId ? "bg-accent/10 ring-1 ring-accent/30" : "hover:bg-panel2")}>
                <button className="min-w-0 flex-1 text-left" onClick={() => open(c.id)}><div className="truncate font-medium">{c.title}</div><div className="truncate text-[11px] text-mute">{c.messages} msgs · {c.tool_calls} tools · {ago(c.updated)}</div></button>
                <button className="opacity-0 transition group-hover:opacity-100" aria-label="Delete conversation" onClick={async () => { try { await api.del(`/api/conversations/${c.id}`); if (c.id === convId) newChat(); qc.invalidateQueries({ queryKey: ["convs"] }); } catch (e: any) { setError(e.message); } }}><Trash2 className="h-3.5 w-3.5 text-mute hover:text-bad" /></button>
              </div>))}
        </div>
      </Card>

      {/* chat */}
      <section className="card flex min-h-0 flex-col">
        <div className="border-b border-line px-4 py-3"><Workflow stage={running || stage !== "idle" ? stage : "idle"} model={model} compact /></div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
          {msgs.length === 0 && !running ? (
            <div className="mx-auto max-w-2xl pt-4">
              <Empty title="Ask anything about your data, docs, code or tools" hint="The assistant plans with the model, then calls real MCP tools. Pick an example to see the pipeline run live." />
              <div className="grid gap-2 sm:grid-cols-2">{EXAMPLES.map((e) => (
                <button key={e.title} onClick={() => send(e.prompt)} className="rounded-lg border border-line bg-panel2/50 p-3 text-left transition hover:border-accent/50 hover:bg-panel2">
                  <div className="text-sm font-medium">{e.title}</div><div className="mt-0.5 text-xs text-mute">{e.prompt}</div>
                  <div className="mt-2 flex flex-wrap gap-1">{e.tools.map((t) => <span key={t} className="rounded bg-bg px-1.5 py-0.5 font-mono text-[10.5px] text-accent">{t}</span>)}</div></button>))}</div>
            </div>
          ) : msgs.map((m, i) => <Bubble key={m.id} m={m} busy={running} last={i === msgs.length - 1 && m.role === "assistant"} onCopy={(t) => navigator.clipboard?.writeText(t)} onRegen={() => convId && run(`/api/conversations/${convId}/regenerate`, {})} />)}
          {running && (
            <div className="flex justify-start"><div className="card max-w-[88%] px-4 py-3 text-sm">
              {live.text ? <Markdown>{live.text}</Markdown> : <div className="flex items-center gap-2 text-mute"><Spinner />{stage === "tool" || stage === "db" ? "Running tool…" : stage === "result" ? "Reading tool result…" : "Thinking…"}</div>}
              <Steps steps={calls} />
            </div></div>)}
          {error && <ErrorBox error={error} />}
          <div ref={bottom} />
        </div>
        <form className="border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <div className="flex items-end gap-2">
            <textarea className="input max-h-40 min-h-[44px] resize-none" rows={1} value={input} disabled={running} placeholder="Message the assistant…" aria-label="Message"
              onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
            {running ? <button type="button" className="btn btn-danger h-11" onClick={stop}><Square className="h-4 w-4" />Stop</button> : <button type="submit" className="btn btn-primary h-11" disabled={!input.trim()}><Send className="h-4 w-4" />Send</button>}
          </div>
          <div className="mt-1.5 flex justify-between text-[11px] text-mute"><span>Enter to send · Shift+Enter for newline · {health.data?.offline_demo ? "Offline demo model: understands simple keyword requests only." : `Model: ${model ?? "Unavailable"}`}</span><span>{input.length}/8000</span></div>
        </form>
      </section>

      {/* inspector */}
      <div className="hidden min-h-0 space-y-4 overflow-y-auto xl:block">
        <Card title="This request" pad>
          {running ? <ul className="space-y-1.5 text-xs">{live.events.filter((e) => e.type === "llm_call" || e.type === "tool_result").map((e, i) => <li key={i} className="flex justify-between"><span className="font-mono">{e.type === "llm_call" ? `LLM call ${e.step ?? ""}` : e.name}</span><span className="text-mute">{ms(e.ms)}</span></li>)}{live.events.length === 0 && <li className="text-mute">Waiting for the model…</li>}</ul> :
            lastCall?.summary ? <p className="text-xs text-mute">{lastCall.summary}</p> : <p className="text-xs text-mute">Metrics appear after the first answer.</p>}
        </Card>
        <Card title="Context window of this chat">
          {ctx.data ? <div className="space-y-1 text-xs"><div className="flex justify-between"><span className="text-mute">Messages sent to model</span><span>{ctx.data.messages_in_context}/{ctx.data.limit_messages}</span></div><div className="flex justify-between"><span className="text-mute">≈ tokens (chars ÷ 4)</span><span>{num(ctx.data.approx_tokens)}</span></div>
            <button className="btn mt-2 w-full" disabled={running} onClick={async () => { await api.post(`/api/conversations/${convId}/clear`, {}); open(convId!); }}><X className="h-3.5 w-3.5" />Clear conversation</button></div> : <p className="text-xs text-mute">Start a conversation to see context usage.</p>}
        </Card>
        <Card title="Persistent memory" right={<Badge tone="info">{mem.data?.count ?? 0}</Badge>}>
          {mem.data?.records?.length ? <ul className="space-y-1.5 text-xs">{mem.data.records.slice(0, 4).map((r: any) => <li key={r.id} className="rounded border border-line bg-bg/60 p-2">{short(r.fact, 90)}</li>)}</ul> : <p className="text-xs text-mute">Nothing remembered yet. Try “Remember that I prefer INR lakhs”.</p>}
          <p className="mt-2 text-[11px] text-mute">Relevant memories are injected into the model prompt each turn.</p>
        </Card>
      </div>
    </div>
  );
}
