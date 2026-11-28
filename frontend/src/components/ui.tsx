"use client";
import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import { ReactNode } from "react";
import { UNAVAILABLE } from "@/lib/format";

export const cx = clsx;

export function Card({ title, right, children, className, pad = true }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx("card", className)}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
          <div className="flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={pad ? "p-4" : ""}>{children}</div>
    </section>
  );
}

type Tone = "ok" | "warn" | "bad" | "info" | "violet" | "mute";
const TONES: Record<Tone, string> = {
  ok: "border-ok/30 bg-ok/10 text-ok", warn: "border-warn/30 bg-warn/10 text-warn", bad: "border-bad/30 bg-bad/10 text-bad",
  info: "border-accent/30 bg-accent/10 text-accent", violet: "border-violet/30 bg-violet/10 text-violet", mute: "border-line bg-panel2 text-mute",
};
export function Badge({ tone = "mute", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium", TONES[tone])}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export const kindTone = (k: string): Tone => (k === "read" ? "ok" : k === "write" ? "warn" : "bad");
export const permTone = (p: string): Tone => (p === "allow" ? "ok" : p === "approve" ? "warn" : "bad");
export const statusTone = (s?: string | null): Tone => (!s ? "mute" : ["ok", "running", "connected", "allow", "indexed", "done"].includes(s) ? "ok" : ["error", "failed", "denied", "down", "declined"].includes(s) ? "bad" : "warn");

export function Stat({ label, value, sub, icon, loading }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; loading?: boolean }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between"><span className="label">{label}</span><span className="text-mute">{icon}</span></div>
      {loading ? <div className="sk mt-3 h-7 w-24" /> : <div className={cx("mt-2 text-2xl font-semibold tracking-tight", value === UNAVAILABLE && "text-mute")}>{value}</div>}
      {sub && <div className="mt-1 text-xs text-mute">{sub}</div>}
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-xl font-semibold tracking-tight">{title}</h1>{sub && <p className="mt-0.5 text-sm text-mute">{sub}</p>}</div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) { return <Loader2 className={cx("h-4 w-4 animate-spin", className)} />; }

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return <div className="space-y-2">{Array.from({ length: rows }).map((_, i) => <div key={i} className="sk h-5" style={{ width: `${95 - i * 9}%` }} />)}</div>;
}

export function Empty({ title, hint, icon, action }: { title: string; hint?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <div className="text-mute">{icon ?? <Inbox className="h-7 w-7" />}</div>
      <div className="text-sm font-medium">{title}</div>
      {hint && <div className="max-w-md text-xs text-mute">{hint}</div>}
      {action}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-start gap-3 rounded-xl border border-bad/30 bg-bad/5 p-4 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
      <div className="min-w-0 flex-1"><div className="font-medium text-bad">Request failed</div><div className="mt-0.5 break-words text-mute">{msg}</div></div>
      {onRetry && <button className="btn" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />Retry</button>}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div role="tablist" className="inline-flex rounded-lg border border-line bg-bg/60 p-0.5">
      {items.map((i) => (
        <button key={i.id} role="tab" aria-selected={value === i.id} onClick={() => onChange(i.id)}
          className={cx("rounded-md px-3 py-1 text-sm transition", value === i.id ? "bg-panel2 text-ink shadow-sm" : "text-mute hover:text-ink")}>{i.label}</button>
      ))}
    </div>
  );
}

export function Table({ head, children, empty }: { head: ReactNode[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="max-h-[560px] overflow-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-sm"><thead><tr>{head.map((h, i) => <th key={i} className="th">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line/70">{children}</tbody></table>
      {empty && <Empty title="No rows" />}
    </div>
  );
}

export function KV({ k, v }: { k: string; v: ReactNode }) {
  return <div className="flex items-baseline justify-between gap-4 border-b border-line/50 py-1.5 text-sm last:border-0"><span className="text-mute">{k}</span><span className="min-w-0 truncate text-right font-mono text-[12.5px]">{v}</span></div>;
}

export function Json({ value, max = 400 }: { value: unknown; max?: number }) {
  return <pre className="max-h-[300px] overflow-auto rounded-lg border border-line bg-bg p-3 font-mono text-xs text-ink/90" style={{ maxHeight: max }}>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
}
