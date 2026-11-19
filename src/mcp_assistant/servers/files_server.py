"""Files & Documents MCP server -- read, search and write inside one sandboxed folder."""
from __future__ import annotations

from datetime import datetime

from .. import config
from ..docs import extract_text, is_supported
from ._common import (
    EXECUTABLE_SUFFIXES, READ, WRITE, assert_not_secret, make_server, resolve_in_root, truncate,
)

ROOT = config.files_root()
mcp = make_server(
    "files",
    "Read, search and write documents inside the user's workspace folder. Paths are relative to that folder.",
)


@mcp.tool(annotations=READ)
def list_directory(path: str = ".") -> str:
    """List files and sub-folders in a workspace directory (path is relative to the workspace root)."""
    target = resolve_in_root(ROOT, path)
    if not target.is_dir():
        raise ValueError(f"'{path}' is not a directory.")
    rows = []
    for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        try:
            assert_not_secret(child)
        except ValueError:
            continue
        rel = child.relative_to(ROOT).as_posix()
        rows.append(f"[dir]  {rel}/" if child.is_dir() else f"[file] {rel}  ({child.stat().st_size:,} bytes)")
    return "\n".join(rows) or "(empty directory)"


@mcp.tool(annotations=READ)
def file_info(path: str) -> str:
    """Show size and last-modified time of a file."""
    target = resolve_in_root(ROOT, path)
    assert_not_secret(target)
    if not target.exists():
        raise ValueError(f"'{path}' does not exist.")
    st = target.stat()
    return f"{path}: {st.st_size:,} bytes, modified {datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')}"


@mcp.tool(annotations=READ)
def read_file(path: str, offset: int = 0, max_chars: int = 12000) -> str:
    """Read a text, Markdown, CSV, code, PDF or DOCX file. Use `offset` to continue a long file."""
    target = resolve_in_root(ROOT, path)
    assert_not_secret(target)
    if not target.is_file():
        raise ValueError(f"'{path}' is not a file.")
    if not is_supported(target):
        raise ValueError(f"Unsupported file type '{target.suffix}'.")
    text = extract_text(target)
    max_chars = max(500, min(max_chars, 30000))
    chunk = text[offset : offset + max_chars]
    more = offset + max_chars < len(text)
    footer = f"\n…[more content: call again with offset={offset + max_chars}; total {len(text):,} chars]" if more else ""
    return chunk + footer


@mcp.tool(annotations=READ)
def search_files(query: str, path: str = ".", max_results: int = 25) -> str:
    """Case-insensitive search over file names and file contents under a folder."""
    base = resolve_in_root(ROOT, path)
    q = query.lower()
    hits: list[str] = []
    for f in sorted(base.rglob("*")):
        if len(hits) >= max_results:
            break
        if not f.is_file() or f.name.startswith(".") or not is_supported(f):
            continue
        try:
            assert_not_secret(f)
            rel = f.relative_to(ROOT).as_posix()
            if q in f.name.lower():
                hits.append(f"{rel}  (file name match)")
            if f.stat().st_size > 2_000_000 or f.suffix.lower() in {".pdf", ".docx"}:
                continue
            for lineno, line in enumerate(extract_text(f).splitlines(), start=1):
                if q in line.lower():
                    hits.append(f"{rel}:{lineno}: {truncate(line.strip(), 160)}")
                    if len(hits) >= max_results:
                        break
        except (ValueError, OSError):
            continue
    return "\n".join(hits) or f"No matches for '{query}'."


@mcp.tool(annotations=WRITE)
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Create a text file in the workspace. Existing files are only replaced when overwrite=true."""
    target = resolve_in_root(ROOT, path)
    assert_not_secret(target)
    if target.suffix.lower() in EXECUTABLE_SUFFIXES:
        raise ValueError("Writing executable/script files is not allowed.")
    if len(content) > 200_000:
        raise ValueError("Content too large (max 200,000 characters).")
    if target.exists() and not overwrite:
        raise ValueError(f"'{path}' already exists. Pass overwrite=true to replace it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content):,} characters to {path}"


if __name__ == "__main__":
    mcp.run()
