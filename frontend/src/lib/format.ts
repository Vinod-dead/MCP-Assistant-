/** Display helpers. Missing values are shown as "Unavailable" -- never as an invented number. */
export const UNAVAILABLE = "Unavailable";
const isNil = (v: unknown): v is null | undefined => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));

export const num = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : new Intl.NumberFormat("en-US").format(v));
export const compact = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v));
export const pct = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : `${(v * 100).toFixed(v === 1 || v === 0 ? 0 : 1)}%`);
export const secs = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`);
export const ms = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
export const usd = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : v === 0 ? "$0.00" : v < 0.01 ? `$${v.toFixed(5)}` : `$${v.toFixed(2)}`);
export const bytes = (v: number | null | undefined) => (isNil(v) ? UNAVAILABLE : v < 1024 ? `${v} B` : v < 1048576 ? `${(v / 1024).toFixed(1)} KB` : `${(v / 1048576).toFixed(1)} MB`);

export function ago(ts?: string | null, now: number = Date.now()): string {
  if (!ts) return UNAVAILABLE;
  const t = Date.parse(ts);
  if (Number.isNaN(t)) return UNAVAILABLE;
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
export const clock = (ts?: string | null) => { const t = ts ? new Date(ts) : null; return t && !Number.isNaN(+t) ? t.toLocaleTimeString([], { hour12: false }) : UNAVAILABLE; };
export const short = (s: string | null | undefined, n = 60) => (!s ? "" : s.length > n ? s.slice(0, n - 1) + "…" : s);
