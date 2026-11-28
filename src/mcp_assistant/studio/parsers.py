"""Turn the text output of the existing file / git MCP tools into structured data for the UI."""
from __future__ import annotations

import re
from typing import Any


def parse_directory(text: str) -> list[dict[str, Any]]:
    """`[dir]  docs/` / `[file] docs/a.md  (1,234 bytes)` -> entries."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(r"^\[(dir|file)\]\s+(.+?)(?:\s+\(([\d,]+) bytes\))?$", line)
        if not m:
            continue
        kind, path, size = m.groups()
        path = path.rstrip("/")
        out.append({"type": kind, "path": path, "name": path.rsplit("/", 1)[-1],
                    "size": int(size.replace(",", "")) if size else None})
    return out


def parse_tree(text: str) -> list[dict[str, Any]]:
    """Indented tree (2 spaces per level, trailing `/` = folder) -> nested nodes."""
    root: list[dict[str, Any]] = []
    stack: list[tuple[int, list[dict[str, Any]], str]] = [(-1, root, "")]
    for line in text.splitlines():
        if not line.strip():
            continue
        level = (len(line) - len(line.lstrip(" "))) // 2
        name = line.strip()
        is_dir = name.endswith("/")
        name = name.rstrip("/")
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_children, parent_path = stack[-1][1], stack[-1][2]
        path = f"{parent_path}/{name}".lstrip("/")
        node: dict[str, Any] = {"name": name, "path": path, "type": "dir" if is_dir else "file"}
        if is_dir:
            node["children"] = []
        parent_children.append(node)
        if is_dir:
            stack.append((level, node["children"], path))
    return root


def parse_git_status(text: str) -> dict[str, Any]:
    """`git status --short --branch` -> branch, ahead/behind and staged / modified / untracked lists."""
    branch, upstream, ahead, behind = None, None, 0, 0
    staged: list[dict[str, str]] = []
    modified: list[dict[str, str]] = []
    untracked: list[dict[str, str]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:]
            if head.startswith("No commits yet on "):
                branch = head.removeprefix("No commits yet on ").strip()
                continue
            m = re.match(r"^(?P<b>.+?)(?:\.\.\.(?P<u>\S+))?(?:\s+\[(?P<s>[^\]]+)\])?$", head)
            if m:
                branch, upstream = m.group("b"), m.group("u")
                status = m.group("s") or ""
                a = re.search(r"ahead (\d+)", status)
                b = re.search(r"behind (\d+)", status)
                ahead, behind = int(a.group(1)) if a else 0, int(b.group(1)) if b else 0
            continue
        if len(line) < 4:
            continue
        x, y, path = line[0], line[1], line[3:]
        entry = {"path": path, "index": x, "worktree": y}
        if x == "?" and y == "?":
            untracked.append(entry)
            continue
        if x in "MADRCU":
            staged.append(entry)
        if y in "MDU":
            modified.append(entry)
    return {"branch": branch, "upstream": upstream, "ahead": ahead, "behind": behind, "staged": staged,
            "modified": modified, "untracked": untracked, "clean": not (staged or modified or untracked)}


def parse_git_log(text: str) -> list[dict[str, str]]:
    """`%h %ad %an: %s` lines."""
    commits: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3 or ": " not in parts[2]:
            continue
        author, subject = parts[2].split(": ", 1)
        commits.append({"hash": parts[0], "date": parts[1], "author": author, "subject": subject})
    return commits


def parse_search_hits(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(r"^(?P<p>.+?):(?P<n>\d+): (?P<t>.*)$", line)
        if m:
            hits.append({"path": m.group("p"), "line": int(m.group("n")), "text": m.group("t")})
            continue
        m = re.match(r"^(?P<p>.+?)\s+\(file name match\)$", line)
        if m:
            hits.append({"path": m.group("p"), "line": None, "text": "(file name match)"})
    return hits
