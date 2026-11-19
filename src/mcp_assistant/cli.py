
"""Interactive terminal assistant: python -m mcp_assistant.cli (or: mcp-assistant)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from . import __version__, config
from .demo_data import ensure_demo_data
from .models import ToolInfo
from .policy import Policy
from .runtime import Runtime, approve_all, build_runtime, resolve_provider

console = Console()

HELP = """[bold]Commands[/bold]
  /tools      list every tool the model can see (and whether it needs approval)
  /servers    MCP server status
  /stats      session metrics: tokens, latency p50/p95, cost per request
  /audit      last audit-log entries
  /memory     saved long-term memories
  /policy     active permission profile
  /reset      clear the conversation
  /help       this help        /quit  exit"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mcp-assistant",
        description="MCP-powered AI assistant",
    )

    p.add_argument(
        "--provider",
        choices=["auto", "nvidia", "gemini", "mock"],
        default="auto",
        help="auto = NVIDIA if its key is set, otherwise Gemini, otherwise offline mock",
    )

    p.add_argument(
        "--model",
        help="Model ID (default from NVIDIA_MODEL or GEMINI_MODEL, depending on provider)",
    )

    p.add_argument(
        "--profile",
        default="standard",
        help="permission profile: readonly | standard | admin",
    )

    p.add_argument(
        "--auto-approve",
        action="store_true",
        help="approve every action without asking (still audited). Use with care.",
    )

    p.add_argument(
        "--reflect",
        action="store_true",
        help="extra self-check pass that verifies answers against tool output",
    )

    p.add_argument(
        "--once",
        metavar="PROMPT",
        help="run a single request and exit",
    )

    p.add_argument(
        "--list-models",
        action="store_true",
        help="list available Gemini models and exit",
    )

    p.add_argument(
        "--version",
        action="version",
        version=f"mcp-assistant {__version__}",
    )

    return p.parse_args(argv)


def _short(obj, n: int = 110) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def on_event(kind: str, data: dict) -> None:
    if kind == "tool_call":
        tag = (
            " [yellow](approved)[/yellow]"
            if data["approval"] == "approve"
            else ""
        )
        console.print(
            f"  [cyan]→ {data['name']}[/cyan] "
            f"[dim]{_short(data['args'])}[/dim]{tag}"
        )

    elif kind == "tool_result":
        mark = "[green]✓[/green]" if data["ok"] else "[red]✗[/red]"
        flag = (
            "  [bold red]⚠ possible prompt injection in content[/bold red]"
            if data["flags"]
            else ""
        )
        console.print(
            f"    {mark} [dim]{data['ms']} ms, "
            f"{data['chars']:,} chars[/dim]{flag}"
        )

    elif kind == "tool_blocked":
        console.print(
            f"  [red]⛔ {data['name']}: {data['status']}[/red] "
            f"[dim]{data['message']}[/dim]"
        )

    elif kind == "reflection":
        console.print(
            f"  [magenta]↺ self-check: {data['verdict'][:80]}[/magenta]"
        )


async def ask_human(info: ToolInfo, args: dict) -> bool:
    kind = "DESTRUCTIVE" if info.destructive else "changes something"

    body = Syntax(
        json.dumps(args, indent=2, ensure_ascii=False)[:1500],
        "json",
        theme="ansi_dark",
    )

    console.print(
        Panel(
            body,
            title=f"[bold yellow]Approval needed[/bold yellow] {info.qualified}",
            subtitle=kind,
            border_style="yellow",
        )
    )

    answer = await asyncio.to_thread(
        console.input,
        "[bold]Allow this action?[/bold] [y/N] ",
    )

    return answer.strip().lower() in {"y", "yes"}


def show_tools(rt: Runtime) -> None:
    table = Table(
        title=f"Tools visible to the model ({rt.policy.profile} profile)"
    )

    for col in ("tool", "kind", "permission"):
        table.add_column(col)

    for tool in sorted(
        rt.agent.visible_tools(),
        key=lambda item: item.qualified,
    ):
        decision, _ = rt.policy.decide(tool)

        kind = (
            "read"
            if tool.read_only
            else ("write (destructive)" if tool.destructive else "write")
        )

        table.add_row(
            tool.qualified,
            kind,
            decision.value,
        )

    console.print(table)


def show_stats(rt: Runtime) -> None:
    stats = rt.metrics.session_summary()

    if stats["turns"] == 0:
        console.print("[dim]No requests yet.[/dim]")
        return

    table = Table(title="Session metrics")
    table.add_column("metric")
    table.add_column("value", justify="right")

    for key, value in stats.items():
        formatted = f"{value:,}" if isinstance(value, int) else str(value)
        table.add_row(key, formatted)

    console.print(table)


async def handle_command(cmd: str, rt: Runtime) -> bool:
    """Returns False to quit."""

    if cmd in {"/quit", "/exit", "/q"}:
        return False

    if cmd == "/help":
        console.print(HELP)

    elif cmd == "/tools":
        show_tools(rt)

    elif cmd == "/servers":
        for name, ok, count, err in rt.hub.status():
            status = "[green]●[/green]" if ok else "[red]●[/red]"
            error = f"[red]{err}[/red]" if err else ""
            console.print(
                f"  {status} {name:<10} {count} tools {error}"
            )

    elif cmd == "/stats":
        show_stats(rt)

    elif cmd == "/audit":
        for record in rt.audit.tail(10):
            timestamp = record["ts"][11:19]
            event = record.get("tool", record.get("event"))
            status = record.get("status", "")
            args = _short(record.get("args", ""), 70)

            console.print(
                f"  [dim]{timestamp}[/dim] {event} "
                f"[bold]{status}[/bold] {args}"
            )

    elif cmd == "/memory":
        items = rt.agent.memory.items

        output = "\n".join(
            f"  {item['id']}: {item['fact']}"
            for item in items
        )

        console.print(output or "[dim]No memories yet.[/dim]")

    elif cmd == "/policy":
        profiles = Policy.profiles(
            config.ROOT / "config" / "policy.yaml"
        )

        console.print(
            f"[bold]{rt.policy.profile}[/bold]: "
            f"{rt.policy.description}\n"
            f"profiles: {', '.join(profiles)}"
        )

    elif cmd == "/reset":
        rt.agent.reset()
        console.print("[dim]Conversation cleared.[/dim]")

    else:
        console.print("[red]Unknown command.[/red] Type /help")

    return True


async def run_once(rt: Runtime, prompt: str) -> None:
    result = await rt.agent.run_turn(prompt)

    console.print(Markdown(result.answer))

    if result.metrics:
        console.print(f"[dim]{result.metrics.summary()}[/dim]")


async def amain(args: argparse.Namespace) -> int:
    # Load environment variables from the project .env file.
    config.load_env()

    # List Gemini models when explicitly requested.
    if args.list_models:
        from .llm.gemini import list_models

        print("\n".join(list_models()))
        return 0

    # Resolve the selected provider.
    provider = resolve_provider(args.provider)

    # Check credentials for the selected provider.
    if provider == "nvidia" and not config.have_nvidia_credentials():
        console.print(
            "[red]No NVIDIA credentials found.[/red] "
            "Put NVIDIA_API_KEY in your .env file."
        )
        return 2

    if provider == "gemini" and not config.have_gemini_credentials():
        console.print(
            "[red]No Gemini credentials found.[/red] "
            "Put GEMINI_API_KEY in your .env file."
        )
        return 2

    # Select the model for the chosen provider.
    if provider == "nvidia":
        model = args.model or os.environ.get("NVIDIA_MODEL")

    elif provider == "gemini":
        model = args.model or os.environ.get("GEMINI_MODEL")

    else:
        model = args.model

    ensure_demo_data(config.data_dir())

    # Start MCP servers and build the runtime.
    with console.status("Starting MCP servers…"):
        rt = await build_runtime(
            provider=provider,
            model=model,
            profile=args.profile,
            approver=(
                approve_all if args.auto_approve else ask_human
            ),
            on_event=on_event,
            reflect=args.reflect,
        )

    try:
        failed = [
            (name, error)
            for name, ok, _, error in rt.hub.status()
            if not ok
        ]

        console.print(
            Panel.fit(
                f"[bold]MCP Assistant[/bold] v{__version__}   "
                f"provider: [cyan]{rt.provider}[/cyan]   "
                f"model: [cyan]{rt.model}[/cyan]   "
                f"profile: [cyan]{rt.policy.profile}[/cyan]\n"
                f"{len(rt.hub.tools)} tools from "
                f"{len(rt.hub.connections) - len(failed)} MCP servers   "
                "type /help",
                border_style="cyan",
            )
        )

        if provider == "mock":
            console.print(
                "[yellow]Offline demo mode:[/yellow] "
                "no NVIDIA or Gemini key found, "
                "so a keyword router stands in for the model."
            )

        for name, error in failed:
            console.print(
                f"[red]Server '{name}' failed to start:[/red] "
                f"{error} [dim](see logs/server-{name}.log)[/dim]"
            )

        if args.once:
            await run_once(rt, args.once)
            return 0

        while True:
            try:
                line = (
                    await asyncio.to_thread(
                        console.input,
                        "\n[bold green]you ›[/bold green] ",
                    )
                ).strip()

            except (EOFError, KeyboardInterrupt):
                break

            if not line:
                continue

            if line.startswith("/"):
                command = line.split()[0].lower()

                if not await handle_command(command, rt):
                    break

                continue

            await run_once(rt, line)

        show_stats(rt)
        return 0

    finally:
        await rt.close()


def main() -> None:
    try:
        sys.exit(asyncio.run(amain(parse_args())))

    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
