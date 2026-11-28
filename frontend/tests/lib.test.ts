import { describe, expect, it } from "vitest";
import { parseSSE } from "@/lib/api";
import { UNAVAILABLE, ago, compact, ms, pct, usd } from "@/lib/format";
import { looksLikeWrite, tokenizeSql } from "@/lib/sql";

describe("parseSSE", () => {
  it("parses complete frames and keeps the partial remainder", () => {
    const { events, rest } = parseSSE('event: token\ndata: {"text":"Hi"}\n\nevent: done\ndata: {"a":1}\n\nevent: tok');
    expect(events).toEqual([{ event: "token", data: { text: "Hi" } }, { event: "done", data: { a: 1 } }]);
    expect(rest).toBe("event: tok");
  });
  it("handles CRLF, multi-line data and skips malformed frames", () => {
    const { events } = parseSSE('event: a\r\ndata: {"x":\r\ndata: 2}\r\n\r\nevent: b\ndata: not-json\n\n');
    expect(events).toEqual([{ event: "a", data: { x: 2 } }]);
  });
});

describe("format", () => {
  it("never invents values", () => {
    for (const f of [compact, pct, ms, usd]) { expect(f(null)).toBe(UNAVAILABLE); expect(f(undefined)).toBe(UNAVAILABLE); expect(f(NaN)).toBe(UNAVAILABLE); }
    expect(ago(null)).toBe(UNAVAILABLE);
    expect(ago("garbage")).toBe(UNAVAILABLE);
  });
  it("formats real values", () => {
    expect(pct(1)).toBe("100%"); expect(pct(0.9567)).toBe("95.7%"); expect(ms(1500)).toBe("1.50 s"); expect(usd(0)).toBe("$0.00");
    expect(ago("2026-01-01T00:00:00Z", Date.parse("2026-01-01T00:02:00Z"))).toBe("2m ago");
  });
});

describe("sql", () => {
  it("tokenizes keywords, strings, numbers, comments", () => {
    const t = tokenizeSql("SELECT name, 42 FROM t WHERE x = 'a''b' -- hi").filter((x) => x.type !== "ws");
    expect(t.map((x) => x.type)).toEqual(["kw", "id", "punct", "num", "kw", "id", "kw", "id", "punct", "str", "cmt"]);
  });
  it("flags write-looking SQL but not words inside strings", () => {
    expect(looksLikeWrite("DELETE FROM customers")).toBe(true);
    expect(looksLikeWrite("SELECT * FROM t WHERE note = 'please delete me'")).toBe(false);
  });
});

import { stageFor } from "@/components/workflow";
describe("workflow stages", () => {
  it("follows the real event order", () => {
    let s: any = "idle";
    const seq: [any, string][] = [[{ type: "start" }, "user"], [{ type: "llm_start" }, "model"], [{ type: "tool_call", name: "db__query" }, "db"],
      [{ type: "tool_result" }, "result"], [{ type: "llm_start" }, "model"], [{ type: "done" }, "answer"]];
    for (const [ev, want] of seq) { s = stageFor(ev, s); expect(s).toBe(want); }
    expect(stageFor({ type: "tool_call", name: "files__read_file" }, "model")).toBe("tool");
  });
});
