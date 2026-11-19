"""Golden-set evaluation: does the assistant pick the right tools and produce the right facts?

    python -m mcp_assistant.evaluate --provider gemini          # real measurement
    python -m mcp_assistant.evaluate --provider mock            # plumbing check only (used in CI)

Each task in eval/golden.yaml can assert:
  expect_any_tool   at least one of these tools must be called
  forbid_tools      none of these may be called
  answer_contains   substrings (case-insensitive) that must appear in the final answer
Exit code is non-zero when accuracy, pass rate or cost fall below the thresholds -- wire it into CI
to stop regressions in accuracy, latency or cost.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

import yaml

from . import config
from .runtime import build_runtime, deny_all, resolve_provider


def _check(task: dict, result) -> dict:
    called = [c["name"] for c in result.tool_calls]
    expect = task.get("expect_any_tool", [])
    tool_ok = (not expect) or any(t in called for t in expect)
    forbid_ok = not any(t in called for t in task.get("forbid_tools", []))
    answer = result.answer.lower()
    contains_ok = all(s.lower() in answer for s in task.get("answer_contains", []))
    return {
        "id": task["id"], "tool_ok": tool_ok, "forbid_ok": forbid_ok, "answer_ok": contains_ok,
        "passed": tool_ok and forbid_ok and contains_ok and result.error is None,
        "called": called, "seconds": round(result.metrics.wall_seconds, 2),
        "in_tokens": result.metrics.input_tokens, "out_tokens": result.metrics.output_tokens,
        "cost_usd": round(result.metrics.est_cost_usd, 6), "error": result.error,
    }


async def run(args: argparse.Namespace) -> int:
    config.load_env()
    provider = resolve_provider(args.provider)
    tasks = yaml.safe_load(Path(args.golden).read_text(encoding="utf-8"))["tasks"]
    report_path = config.logs_dir() / "eval_report.json"  # resolved BEFORE we redirect logs to a temp dir

    # Isolated data dir so evals never touch real memory / index; copy demo DB in
    tmp = Path(tempfile.mkdtemp(prefix="mcp-eval-"))
    os.environ["MCP_ASSISTANT_DATA"] = str(tmp)
    os.environ["MCP_ASSISTANT_LOGS"] = str(tmp / "logs")
    from .demo_data import ensure_demo_data

    ensure_demo_data(tmp)
    os.environ["DISABLE_EMBEDDINGS"] = "true"  # keep evals deterministic and cheap

    rt = await build_runtime(provider=provider, model=args.model or os.environ.get("GEMINI_MODEL"),
                             profile=args.profile, approver=deny_all)  # writes are attempted, never executed
    rows = []
    try:
        for task in tasks:
            rt.agent.reset()
            result = await rt.agent.run_turn(task["prompt"])
            row = _check(task, result)
            rows.append(row)
            print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['id']:<28} tools={row['called']}  {row['seconds']}s")
    finally:
        await rt.close()
        shutil.rmtree(tmp, ignore_errors=True)

    n = len(rows)
    tool_acc = sum(r["tool_ok"] and r["forbid_ok"] for r in rows) / n
    pass_rate = sum(r["passed"] for r in rows) / n
    lat = sorted(r["seconds"] for r in rows)
    summary = {
        "provider": provider, "model": rt.model, "tasks": n,
        "tool_selection_accuracy": round(tool_acc, 3), "task_pass_rate": round(pass_rate, 3),
        "latency_p50_s": round(statistics.median(lat), 2), "latency_p95_s": lat[min(n - 1, int(round(0.95 * (n - 1))))],
        "avg_cost_per_request_usd": round(sum(r["cost_usd"] for r in rows) / n, 5),
        "avg_tokens_per_request": round(sum(r["in_tokens"] + r["out_tokens"] for r in rows) / n),
    }
    print("\n" + json.dumps(summary, indent=2))
    report_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(f"report -> {report_path}")

    failures = []
    if tool_acc < args.min_tool_acc:
        failures.append(f"tool-selection accuracy {tool_acc:.2f} < {args.min_tool_acc}")
    if pass_rate < args.min_pass:
        failures.append(f"task pass rate {pass_rate:.2f} < {args.min_pass}")
    if args.max_cost and summary["avg_cost_per_request_usd"] > args.max_cost:
        failures.append(f"avg cost ${summary['avg_cost_per_request_usd']} > ${args.max_cost}")
    if failures:
        print("EVAL GATE FAILED: " + "; ".join(failures))
        return 1
    print("EVAL GATE PASSED")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Run the golden-set evaluation")
    p.add_argument("--provider", choices=["auto", "gemini", "mock"], default="auto")
    p.add_argument("--model")
    p.add_argument("--profile", default="standard")
    p.add_argument("--golden", default=str(config.ROOT / "eval" / "golden.yaml"))
    p.add_argument("--min-tool-acc", type=float, default=0.85)
    p.add_argument("--min-pass", type=float, default=0.75)
    p.add_argument("--max-cost", type=float, default=0.0, help="fail if avg est. cost per request exceeds this (USD); 0 = off")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
