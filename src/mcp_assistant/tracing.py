"""LLM-native metrics and per-turn traces: tokens, tokens/sec, latency, cost per request."""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def load_pricing(path: Path) -> dict[str, Any]:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


@dataclass
class TurnMetrics:
    question: str
    started: float = field(default_factory=time.perf_counter)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_seconds: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    tool_blocked: int = 0
    tool_seconds: float = 0.0
    est_cost_usd: float = 0.0
    wall_seconds: float = 0.0
    spans: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tokens_per_sec(self) -> float:
        return self.output_tokens / self.llm_seconds if self.llm_seconds >= 0.05 else 0.0

    def summary(self) -> str:
        speed = f"{self.tokens_per_sec:.0f} tok/s" if self.tokens_per_sec else "tok/s n/a"
        return (
            f"{self.llm_calls} LLM call(s) | {self.input_tokens:,} in / {self.output_tokens:,} out tokens | "
            f"{speed} | {self.tool_calls} tool call(s) | "
            f"{self.wall_seconds:.1f}s | est ${self.est_cost_usd:.4f}"
        )


class Metrics:
    def __init__(self, model: str, pricing: dict[str, Any], trace_path: Path | None = None) -> None:
        self.model = model
        self.pricing = pricing
        self.trace_path = trace_path
        self.turns: list[TurnMetrics] = []

    def start_turn(self, question: str) -> TurnMetrics:
        return TurnMetrics(question=question)

    def _price(self) -> tuple[float, float]:
        models = self.pricing.get("models", {})
        entry = models.get(self.model) or self.pricing.get("default") or {}
        return float(entry.get("input_per_million", 0)), float(entry.get("output_per_million", 0))

    def add_llm(self, turn: TurnMetrics, in_tok: int, out_tok: int, seconds: float) -> None:
        p_in, p_out = self._price()
        turn.llm_calls += 1
        turn.input_tokens += in_tok
        turn.output_tokens += out_tok
        turn.llm_seconds += seconds
        turn.est_cost_usd += in_tok * p_in / 1e6 + out_tok * p_out / 1e6
        turn.spans.append({"type": "llm", "seconds": round(seconds, 3), "in": in_tok, "out": out_tok})

    def add_tool(self, turn: TurnMetrics, name: str, seconds: float, ok: bool, chars: int) -> None:
        turn.tool_calls += 1
        turn.tool_seconds += seconds
        if not ok:
            turn.tool_errors += 1
        turn.spans.append({"type": "tool", "name": name, "seconds": round(seconds, 3), "ok": ok, "chars": chars})

    def finish_turn(self, turn: TurnMetrics) -> None:
        turn.wall_seconds = time.perf_counter() - turn.started
        self.turns.append(turn)
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "question": turn.question[:200],
                "wall_seconds": round(turn.wall_seconds, 3),
                "llm_calls": turn.llm_calls,
                "input_tokens": turn.input_tokens,
                "output_tokens": turn.output_tokens,
                "tokens_per_sec": round(turn.tokens_per_sec, 1),
                "tool_calls": turn.tool_calls,
                "est_cost_usd": round(turn.est_cost_usd, 6),
                "spans": turn.spans,
            }
            with self.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")

    def session_summary(self) -> dict[str, Any]:
        if not self.turns:
            return {"turns": 0}
        walls = sorted(t.wall_seconds for t in self.turns)
        p95 = walls[min(len(walls) - 1, int(round(0.95 * (len(walls) - 1))))]
        tool_calls = sum(t.tool_calls for t in self.turns)
        return {
            "turns": len(self.turns),
            "input_tokens": sum(t.input_tokens for t in self.turns),
            "output_tokens": sum(t.output_tokens for t in self.turns),
            "llm_calls": sum(t.llm_calls for t in self.turns),
            "tool_calls": tool_calls,
            "tool_error_rate": round(sum(t.tool_errors for t in self.turns) / tool_calls, 3) if tool_calls else 0.0,
            "latency_p50_s": round(statistics.median(walls), 2),
            "latency_p95_s": round(p95, 2),
            "avg_cost_per_request_usd": round(sum(t.est_cost_usd for t in self.turns) / len(self.turns), 5),
            "total_cost_usd": round(sum(t.est_cost_usd for t in self.turns), 5),
        }
