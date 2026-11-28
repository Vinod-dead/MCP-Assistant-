"use client";
import { motion } from "framer-motion";
import { Bot, Database, MessageSquare, Sparkles, Wrench, FileOutput } from "lucide-react";
import { cx } from "./ui";

export type Stage = "idle" | "user" | "model" | "tool" | "db" | "result" | "answer";
const STEPS: { id: Exclude<Stage, "idle">; label: string; sub: string; icon: any }[] = [
  { id: "user", label: "User", sub: "your question", icon: MessageSquare },
  { id: "model", label: "NVIDIA Nemotron", sub: "plans the tool call", icon: Bot },
  { id: "tool", label: "MCP tool", sub: "policy → approval → call", icon: Wrench },
  { id: "db", label: "Database", sub: "read-only SQL", icon: Database },
  { id: "result", label: "Tool result", sub: "redacted + scanned", icon: FileOutput },
  { id: "answer", label: "AI response", sub: "grounded answer", icon: Sparkles },
];
const ORDER = STEPS.map((s) => s.id);

/** The pipeline diagram. `stage` is driven by real events from the chat stream (or null for the static explainer). */
export function Workflow({ stage = "idle", model, usedDb = true, compact }: { stage?: Stage; model?: string; usedDb?: boolean; compact?: boolean }) {
  const idx = stage === "idle" ? -1 : ORDER.indexOf(stage);
  return (
    <div className={cx("flex items-stretch gap-1 overflow-x-auto", compact ? "text-[11px]" : "text-xs")} role="list" aria-label="Request pipeline">
      {STEPS.map((s, i) => {
        const done = idx > i, cur = idx === i, skipped = !usedDb && s.id === "db";
        return (
          <div key={s.id} className="flex items-center gap-1" role="listitem">
            <motion.div animate={cur ? { scale: [1, 1.04, 1] } : { scale: 1 }} transition={{ repeat: cur ? Infinity : 0, duration: 1.4 }}
              className={cx("rounded-lg border px-2.5 py-2 transition", compact ? "min-w-[78px]" : "min-w-[112px]", cur ? "border-accent bg-accent/10 shadow-glow" : done ? "border-ok/40 bg-ok/5" : "border-line bg-panel2/60", skipped && "opacity-40")}>
              <s.icon className={cx("mb-1 h-4 w-4", cur ? "text-accent" : done ? "text-ok" : "text-mute")} />
              <div className="font-medium leading-tight">{s.id === "model" && model ? <span title={model}>{model.split("/").pop()}</span> : s.label}</div>
              {!compact && <div className="mt-0.5 text-[10.5px] leading-tight text-mute">{s.sub}</div>}
            </motion.div>
            {i < STEPS.length - 1 && <span className={cx("text-lg", done ? "text-ok" : cur ? "text-accent" : "text-line")}>→</span>}
          </div>
        );
      })}
    </div>
  );
}

/** Maps a streamed event to the pipeline stage (pure, unit-tested). */
export function stageFor(ev: { type: string; name?: string }, current: Stage): Stage {
  switch (ev.type) {
    case "start": case "request_received": return "user";
    case "llm_start": return current === "result" || current === "tool" || current === "db" ? "model" : "model";
    case "tool_call": return (ev.name ?? "").startsWith("db__") ? "db" : "tool";
    case "approval": return "tool";
    case "tool_result": case "tool_blocked": return "result";
    case "token": return current === "result" || current === "answer" ? "answer" : current === "idle" || current === "user" ? "model" : current;
    case "done": return "answer";
    default: return current;
  }
}
