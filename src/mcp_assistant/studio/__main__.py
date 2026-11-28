"""Run the Studio:  python -m mcp_assistant.studio   (or:  mcp-assistant-studio)"""
from __future__ import annotations

import argparse
import sys
import webbrowser

from .app import LOOPBACK, create_app


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mcp-assistant-studio", description="MCP Assistant Studio (dashboard + API)")
    p.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1 -- this UI can trigger real actions")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--provider", choices=["auto", "nvidia", "gemini", "mock"], default="auto",
                   help="auto = NVIDIA if its key is set, else Gemini, else offline mock")
    p.add_argument("--model", help="model id (default: NVIDIA_MODEL / GEMINI_MODEL / built-in default)")
    p.add_argument("--profile", default="standard", help="permission profile: readonly | standard | admin")
    p.add_argument("--reflect", action="store_true", help="extra self-check pass over each answer")
    p.add_argument("--dev", action="store_true", help="allow CORS from http://localhost:3000 (for `npm run dev`)")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)

    if args.host not in LOOPBACK and args.host != "::1":
        print(f"WARNING: binding to {args.host}. The Host-header check will still reject non-localhost names, "
              "and anyone who can reach this port could try to use the session token. Keep it on 127.0.0.1.", file=sys.stderr)

    import uvicorn

    app = create_app(provider=args.provider, model=args.model, profile=args.profile, reflect=args.reflect, dev=args.dev)
    url = f"http://localhost:{args.port}"
    print(f"MCP Assistant Studio → {url}   (API docs: {url}/api/docs · Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
