import { tokenizeSql } from "@/lib/sql";
const CLS: Record<string, string> = { kw: "text-violet font-semibold", str: "text-ok", num: "text-warn", cmt: "text-mute italic", id: "text-ink", punct: "text-mute", ws: "" };
export function SqlView({ sql, className }: { sql: string; className?: string }) {
  return <pre className={`overflow-x-auto whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed ${className ?? ""}`}>{tokenizeSql(sql).map((t, i) => <span key={i} className={CLS[t.type]}>{t.text}</span>)}</pre>;
}
