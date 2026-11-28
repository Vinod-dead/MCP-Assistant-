"""Copy the Next.js static export (frontend/out) into the Python package so `mcp-assistant-studio` can serve it.
Usage:  cd frontend && npm install && npm run build && cd .. && python scripts/sync_frontend.py"""
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src, dst = root / "frontend" / "out", root / "src" / "mcp_assistant" / "studio" / "web"
if not (src / "index.html").exists():
    sys.exit("frontend/out/index.html not found -- run `npm run build` in frontend/ first.")
if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst)
print(f"Copied {sum(1 for _ in dst.rglob('*') if _.is_file())} files -> {dst}")
