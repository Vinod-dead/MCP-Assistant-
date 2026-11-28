"""Analytics built only from what was actually recorded: logs/traces.jsonl (one line per request) and
logs/audit.jsonl (one line per tool decision). Anything not recorded is reported as unavailable."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MAX_LINES = 5000


def read_jsonl(path: Path, limit: int = MAX_LINES) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 3)


def build(traces_path: Path, audit_path: Path) -> dict[str, Any]:
    traces = read_jsonl(traces_path)
    audit = [e for e in read_jsonl(audit_path) if e.get("event") == "tool_call"]
    with_ts = [t for t in traces if t.get("ts")]
    requests = [{
        "index": i + 1, "ts": t.get("ts"), "model": t.get("model") or "unknown", "question": t.get("question", "")[:80],
        "input_tokens": t.get("input_tokens", 0), "output_tokens": t.get("output_tokens", 0),
        "cost_usd": t.get("est_cost_usd", 0.0), "latency_s": t.get("wall_seconds", 0.0), "tokens_per_sec": t.get("tokens_per_sec", 0.0),
        "tool_calls": t.get("tool_calls", 0), "llm_calls": t.get("llm_calls", 0),
    } for i, t in enumerate(traces)]

    per_day: dict[str, dict[str, Any]] = defaultdict(lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency": []})
    for r in requests:
        if not r["ts"]:
            continue
        d = per_day[r["ts"][:10]]
        d["requests"] += 1
        d["input_tokens"] += r["input_tokens"]
        d["output_tokens"] += r["output_tokens"]
        d["cost_usd"] += r["cost_usd"]
        d["latency"].append(r["latency_s"])
    daily = [{"date": k, "requests": v["requests"], "input_tokens": v["input_tokens"], "output_tokens": v["output_tokens"],
              "cost_usd": round(v["cost_usd"], 6), "avg_latency_s": round(statistics.mean(v["latency"]), 2)} for k, v in sorted(per_day.items())]

    tool_stats: dict[str, Counter] = defaultdict(Counter)
    server_stats: dict[str, Counter] = defaultdict(Counter)
    for e in audit:
        name, status = e.get("tool", "?"), e.get("status", "?")
        bucket = "ok" if status == "ok" else ("error" if status == "error" else "blocked")
        tool_stats[name][bucket] += 1
        server_stats[name.split("__", 1)[0]][bucket] += 1
    tools = sorted(({"tool": k, "calls": sum(c.values()), "ok": c["ok"], "errors": c["error"], "blocked": c["blocked"],
                     "error_rate": round(c["error"] / max(1, c["ok"] + c["error"]), 3)} for k, c in tool_stats.items()),
                   key=lambda r: -r["calls"])
    servers = sorted(({"server": k, "calls": sum(c.values()), "ok": c["ok"], "errors": c["error"], "blocked": c["blocked"]} for k, c in server_stats.items()),
                     key=lambda r: -r["calls"])

    models: dict[str, dict[str, Any]] = defaultdict(lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    for r in requests:
        m = models[r["model"]]
        m["requests"] += 1
        m["input_tokens"] += r["input_tokens"]
        m["output_tokens"] += r["output_tokens"]
        m["cost_usd"] += r["cost_usd"]

    lat = [r["latency_s"] for r in requests]
    run = [e for e in audit if e.get("status") in {"ok", "error"}]
    return {
        "totals": {
            "requests": len(requests), "input_tokens": sum(r["input_tokens"] for r in requests),
            "output_tokens": sum(r["output_tokens"] for r in requests), "cost_usd": round(sum(r["cost_usd"] for r in requests), 6),
            "avg_latency_s": round(statistics.mean(lat), 2) if lat else None, "p95_latency_s": _pct(lat, 0.95),
            "tool_calls": len(run), "tool_success_rate": round(sum(1 for e in run if e["status"] == "ok") / len(run), 3) if run else None,
        },
        "requests": requests[-200:], "daily": daily,
        "tools": tools[:30], "servers": servers,
        "models": [{"model": k, "requests": v["requests"], "input_tokens": v["input_tokens"], "output_tokens": v["output_tokens"],
                    "cost_usd": round(v["cost_usd"], 6)} for k, v in models.items()],
        "coverage": {
            "requests_with_timestamp": len(with_ts), "requests_without_timestamp": len(traces) - len(with_ts),
            "note": ("Some older requests were recorded before timestamps/model names were added; they appear in per-request charts "
                     "but not in per-day charts." if len(traces) != len(with_ts) else None),
        },
    }
