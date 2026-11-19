"""Code Repositories MCP server -- browse/search a local repo, read git history, talk to GitHub."""
from __future__ import annotations

import os
import re
import subprocess

from .. import config
from ._common import READ, READ_EXTERNAL, WRITE_EXTERNAL, assert_not_secret, make_server, resolve_in_root, safe_request, truncate

ROOT = config.repo_root()
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build", "logs", "data"}
mcp = make_server("repo", "Explore, search and inspect a code repository (local git repo and GitHub).")
_REF = re.compile(r"^[\w./~^@{}\-]+$")


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=20,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"},
        )
    except FileNotFoundError as exc:
        raise ValueError("git is not installed or not on PATH.") from exc
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or "git command failed (is this folder a git repository?)")
    return proc.stdout


@mcp.tool(annotations=READ)
def repo_tree(path: str = ".", depth: int = 2) -> str:
    """Show the folder tree of the repository (skips .git, node_modules, virtualenvs)."""
    base = resolve_in_root(ROOT, path)
    lines: list[str] = []

    def walk(d, level):
        if level > depth or len(lines) > 300:
            return
        for c in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if c.name in SKIP_DIRS or c.name.startswith(".") and c.name not in {".github"}:
                continue
            lines.append("  " * level + c.name + ("/" if c.is_dir() else ""))
            if c.is_dir():
                walk(c, level + 1)

    walk(base, 0)
    return "\n".join(lines) or "(empty)"


@mcp.tool(annotations=READ)
def read_code(path: str, start_line: int = 1, end_line: int = 200) -> str:
    """Read a source file with line numbers."""
    f = resolve_in_root(ROOT, path)
    assert_not_secret(f)
    if not f.is_file():
        raise ValueError(f"'{path}' is not a file.")
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, start_line)
    end = min(len(lines), max(start, min(end_line, start + 399)))
    body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
    return f"{path} (lines {start}-{end} of {len(lines)})\n{body}"


@mcp.tool(annotations=READ)
def search_code(pattern: str, glob: str = "*", max_results: int = 40) -> str:
    """Regex search across the repository (case-insensitive). `glob` filters file names, e.g. '*.py'."""
    if len(pattern) > 200:
        raise ValueError("Pattern too long.")
    rx = re.compile(pattern, re.I)
    hits: list[str] = []
    for f in sorted(ROOT.rglob(glob)):
        if len(hits) >= max_results:
            break
        if not f.is_file() or any(p in SKIP_DIRS for p in f.relative_to(ROOT).parts) or f.stat().st_size > 1_000_000:
            continue
        try:
            assert_not_secret(f)
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(ROOT).as_posix()}:{n}: {truncate(line.strip(), 160)}")
                    if len(hits) >= max_results:
                        break
        except (UnicodeDecodeError, ValueError, OSError):
            continue
    return "\n".join(hits) or "No matches."


@mcp.tool(annotations=READ)
def git_status() -> str:
    """Show the working-tree status (short format)."""
    return _git("status", "--short", "--branch") or "(clean)"


@mcp.tool(annotations=READ)
def git_log(n: int = 10, path: str = "") -> str:
    """Show the last n commits (optionally only those touching a path)."""
    args = ["log", f"-n{max(1, min(n, 50))}", "--pretty=format:%h %ad %an: %s", "--date=short"]
    if path:
        resolve_in_root(ROOT, path)
        args += ["--", path]
    return _git(*args) or "(no commits)"


@mcp.tool(annotations=READ)
def git_diff(ref: str = "HEAD", path: str = "") -> str:
    """Show a diff of the working tree against a ref (default HEAD)."""
    if not _REF.match(ref) or ref.startswith("-"):
        raise ValueError("Invalid ref.")
    args = ["diff", ref]
    if path:
        resolve_in_root(ROOT, path)
        args += ["--", path]
    return truncate(_git(*args) or "(no changes)", 12000)


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def _check_repo(repo: str) -> None:
    if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo):
        raise ValueError("repo must look like 'owner/name'.")


@mcp.tool(annotations=READ_EXTERNAL)
def github_list_issues(repo: str, state: str = "open", limit: int = 10) -> str:
    """List issues of a GitHub repository ('owner/name'). Public repos work without a token."""
    _check_repo(repo)
    resp = safe_request("GET", f"https://api.github.com/repos/{repo}/issues", headers=_gh_headers(),
                        params={"state": state, "per_page": max(1, min(limit, 30))})
    if resp.status_code != 200:
        raise ValueError(f"GitHub returned {resp.status_code}: {resp.text[:200]}")
    rows = [f"#{i['number']} [{i['state']}] {i['title']}  ({i['html_url']})" for i in resp.json() if "pull_request" not in i]
    return "\n".join(rows) or "No issues."


@mcp.tool(annotations=WRITE_EXTERNAL)
def github_create_issue(repo: str, title: str, body: str = "") -> str:
    """Create an issue in a GitHub repository. Requires GITHUB_TOKEN. Needs human approval."""
    _check_repo(repo)
    if not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("GITHUB_TOKEN is not configured.")
    resp = safe_request("POST", f"https://api.github.com/repos/{repo}/issues", headers=_gh_headers(),
                        json={"title": title, "body": body})
    if resp.status_code not in (200, 201):
        raise ValueError(f"GitHub returned {resp.status_code}: {resp.text[:200]}")
    return f"Created issue #{resp.json()['number']}: {resp.json()['html_url']}"


if __name__ == "__main__":
    mcp.run()
