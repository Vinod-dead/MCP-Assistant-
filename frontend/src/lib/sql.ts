/** Tiny SQL tokenizer for syntax highlighting (no dependency). Pure and unit-tested. */
export type SqlToken = { type: "kw" | "str" | "num" | "cmt" | "id" | "ws" | "punct"; text: string };
const KW = new Set("select from where and or not in is null like ilike join left right inner outer full cross on as group by order having limit offset distinct union all case when then else end with asc desc count sum avg min max round between exists over partition cast explain".split(" "));

export function tokenizeSql(sql: string): SqlToken[] {
  const out: SqlToken[] = [];
  const rx = /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*'?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+)|([\s\S])/g;
  let m: RegExpExecArray | null;
  while ((m = rx.exec(sql))) {
    if (m[1]) out.push({ type: "cmt", text: m[1] });
    else if (m[2]) out.push({ type: "str", text: m[2] });
    else if (m[3]) out.push({ type: "num", text: m[3] });
    else if (m[4]) out.push({ type: KW.has(m[4].toLowerCase()) ? "kw" : "id", text: m[4] });
    else if (m[5]) out.push({ type: "ws", text: m[5] });
    else out.push({ type: "punct", text: m[6] });
  }
  return out;
}

/** Client-side hint only. The server's guard (security.assert_read_only + a read-only connection) is the real enforcement. */
export function looksLikeWrite(sql: string): boolean {
  return /\b(insert|update|delete|drop|alter|create|truncate|replace|attach|pragma|grant|revoke|vacuum)\b/i.test(sql.replace(/'(?:[^']|'')*'/g, "''"));
}
