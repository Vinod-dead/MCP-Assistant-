"""Data endpoints: database explorer, memory, knowledge base, files and repository."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config
from ..docs import is_supported
from ..memory import MemoryStore
from ..policy import Decision
from ..retrieval import KnowledgeIndex, default_embedder, tokenize
from ..security import redact_secrets
from .deps import guard, run_db, studio
from .executor import governed_call, read_tool
from .parsers import parse_directory, parse_git_log, parse_git_status, parse_search_hits, parse_tree

router = APIRouter(prefix="/api", dependencies=[Depends(guard)])


# ======================================================================== database
def _dbx(request: Request):
    state = studio(request)
    tool = state.runtime.hub.tools.get("db__query")
    if tool is not None and state.runtime.policy.decide(tool)[0] is Decision.DENY:
        raise HTTPException(403, "Database access is blocked by the current permission profile.")
    return request.app.state.dbx


@router.get("/database/overview")
async def db_overview(request: Request) -> dict[str, Any]:
    return await run_db(request, _dbx(request).info)


@router.get("/database/tables")
async def db_tables(request: Request) -> dict[str, Any]:
    try:
        return {"tables": await run_db(request, _dbx(request).tables)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, redact_secrets(f"{type(exc).__name__}: {exc}")[:300])


@router.get("/database/schema/{table}")
async def db_schema(table: str, request: Request) -> dict[str, Any]:
    try:
        return await run_db(request, _dbx(request).schema, table)
    except KeyError:
        raise HTTPException(404, f"Unknown table '{table}'.")


@router.get("/database/relations")
async def db_relations(request: Request) -> dict[str, Any]:
    return await run_db(request, _dbx(request).relations)


class FilterSpec(BaseModel):
    column: str
    op: Literal["eq", "ne", "contains", "startswith", "gt", "gte", "lt", "lte", "null", "notnull"]
    value: str | float | int | None = None


class BrowseBody(BaseModel):
    table: str
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=200)
    sort: str | None = None
    order: Literal["asc", "desc"] = "asc"
    search: str = Field("", max_length=200)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=10)


@router.post("/database/browse")
async def db_browse(body: BrowseBody, request: Request) -> dict[str, Any]:
    try:
        return await run_db(request, _dbx(request).browse, body.table, body.page, body.page_size, body.sort, body.order, body.search,
                                       [f.model_dump() for f in body.filters])
    except KeyError:
        raise HTTPException(404, f"Unknown table '{body.table}'.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class SqlBody(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20000)
    max_rows: int = Field(200, ge=1, le=1000)


@router.post("/database/query")
async def db_query(body: SqlBody, request: Request) -> dict[str, Any]:
    """Read-only SQL. Anything but one SELECT/WITH/EXPLAIN is rejected by the shared guard (and the connection is read-only)."""
    state = studio(request)
    dbx = _dbx(request)
    result = await run_db(request, dbx.run_sql, body.sql, body.max_rows)
    state.audit_write(event="db_explorer_query", status="ok" if result["ok"] else "error", sql=redact_secrets(body.sql)[:300],
                      ms=result["ms"], rows=result["row_count"], source="explorer", error=result["error"])
    return result


@router.get("/database/history")
async def db_history(request: Request) -> dict[str, Any]:
    return {"history": request.app.state.dbx.history(50)}


# ======================================================================== memory
def _memory_path():
    return config.data_dir() / "memory.json"


@router.get("/memory")
async def memory_list(request: Request) -> dict[str, Any]:
    items = MemoryStore(_memory_path()).items  # always re-read from disk: the memory MCP server writes this file
    return {"records": list(reversed(items)), "count": len(items), "file": "data/memory.json",
            "supports": {"create": "memory__remember", "update": False, "delete": "memory__forget (needs approval in the standard profile)"}}


@router.get("/memory/search")
async def memory_search(q: str, request: Request, k: int = 5) -> dict[str, Any]:
    hits = MemoryStore(_memory_path()).search(q[:300], max(1, min(k, 20)))
    return {"query": q, "terms": tokenize(q), "results": [{"rank": i + 1, **m} for i, m in enumerate(hits)]}


class MemoryBody(BaseModel):
    fact: str = Field(..., min_length=1, max_length=500)
    tags: str = Field("", max_length=200)


@router.post("/memory")
async def memory_add(body: MemoryBody, request: Request) -> dict[str, Any]:
    return await governed_call(studio(request), "memory__remember", {"fact": body.fact, "tags": body.tags}, source="manual")


@router.delete("/memory/{memory_id}")
async def memory_delete(memory_id: str, request: Request) -> dict[str, Any]:
    return await governed_call(studio(request), "memory__forget", {"memory_id": memory_id}, source="manual")


# ======================================================================== knowledge
def _index_path():
    return config.data_dir() / "knowledge" / "index.json"


@router.get("/knowledge")
async def knowledge(request: Request) -> dict[str, Any]:
    idx = KnowledgeIndex(_index_path())
    root = config.files_root()
    per_doc: dict[str, dict[str, int]] = {}
    for c in idx.chunks:
        d = per_doc.setdefault(c["source"], {"chunks": 0, "vectors": 0, "chars": 0})
        d["chunks"] += 1
        d["chars"] += len(c["text"])
        d["vectors"] += 1 if c.get("vec") else 0
    docs = []
    seen = set()
    for source, mtime in sorted(idx.files.items()):
        f = root / source
        status = "indexed"
        if not f.exists():
            status = "source missing"
        elif f.stat().st_mtime != mtime:
            status = "stale (file changed since indexing)"
        seen.add(source)
        docs.append({"source": source, "status": status, "indexed_at": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds"),
                     **per_doc.get(source, {"chunks": 0, "vectors": 0, "chars": 0})})
    unindexed = []
    if root.exists():
        for f in sorted(root.rglob("*")):
            if f.is_file() and not f.name.startswith(".") and is_supported(f):
                rel = f.relative_to(root).as_posix()
                if rel not in seen:
                    unindexed.append({"source": rel, "status": "not indexed", "chunks": 0, "vectors": 0, "chars": 0, "indexed_at": None})
    embeddings = config.have_gemini_credentials() and not (__import__("os").environ.get("DISABLE_EMBEDDINGS", "").lower() in {"1", "true"})
    return {"documents": docs + unindexed, "chunks": len(idx.chunks), "with_embeddings": sum(1 for c in idx.chunks if c.get("vec")),
            "mode": "hybrid (keyword + Gemini embeddings)" if embeddings else "keyword only (BM25) -- embeddings need GEMINI_API_KEY",
            "root": str(root)}


class IndexBody(BaseModel):
    path: str = Field(".", max_length=300)


@router.post("/knowledge/index")
async def knowledge_index(body: IndexBody, request: Request) -> dict[str, Any]:
    return await governed_call(studio(request), "knowledge__index_folder", {"path": body.path}, source="manual")


class KnowledgeSearch(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    k: int = Field(5, ge=1, le=10)


@router.post("/knowledge/search")
async def knowledge_search(body: KnowledgeSearch, request: Request) -> dict[str, Any]:
    """Same retrieval code as the `knowledge__search_knowledge` MCP tool, but returning structured scores."""
    def run() -> dict[str, Any]:
        idx = KnowledgeIndex(_index_path())
        embedder = default_embedder()
        terms = tokenize(body.query)
        hits = idx.search(body.query, k=body.k, embedder=embedder) if idx.chunks else []
        for h in hits:
            words = set(tokenize(h["text"]))
            h["matched_terms"] = [t for t in dict.fromkeys(terms) if t in words]
        return {"query": body.query, "steps": {"query_terms": terms, "chunks_searched": len(idx.chunks), "documents": len(idx.files),
                                                "embedder": "gemini" if embedder else None,
                                                "mode": hits[0]["mode"] if hits else ("lexical" if idx.chunks else "empty index")},
                "results": hits, "index_empty": not idx.chunks}
    return await asyncio.to_thread(run)


# ======================================================================== files
@router.get("/files")
async def files_list(request: Request, path: str = ".") -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "files__list_directory", {"path": path})
    if not ok:
        raise HTTPException(400, text)
    return {"path": path, "entries": parse_directory(text), "root": "workspace (FILES_ROOT)"}


@router.get("/files/read")
async def files_read(request: Request, path: str, offset: int = 0) -> dict[str, Any]:
    state = studio(request)
    ok, text = await read_tool(state, "files__read_file", {"path": path, "offset": max(0, offset)})
    if not ok:
        raise HTTPException(400, text)
    _, info = await read_tool(state, "files__file_info", {"path": path})
    return {"path": path, "content": text, "info": info, "offset": offset}


@router.get("/files/search")
async def files_search(request: Request, q: str, path: str = ".") -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "files__search_files", {"query": q[:200], "path": path})
    if not ok:
        raise HTTPException(400, text)
    return {"query": q, "hits": parse_search_hits(text)}


# ======================================================================== repository
@router.get("/repo/status")
async def repo_status(request: Request) -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "repo__git_status")
    if not ok:
        return {"available": False, "error": text}
    return {"available": True, **parse_git_status(text), "raw": text}


@router.get("/repo/log")
async def repo_log(request: Request, n: int = 15, path: str = "") -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "repo__git_log", {"n": max(1, min(n, 50)), "path": path})
    return {"available": ok, "error": None if ok else text, "commits": parse_git_log(text) if ok else []}


@router.get("/repo/diff")
async def repo_diff(request: Request, ref: str = "HEAD", path: str = "") -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "repo__git_diff", {"ref": ref, "path": path})
    return {"available": ok, "error": None if ok else text, "diff": text if ok else ""}


@router.get("/repo/tree")
async def repo_tree(request: Request, path: str = ".", depth: int = 3) -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "repo__repo_tree", {"path": path, "depth": max(1, min(depth, 5))})
    if not ok:
        raise HTTPException(400, text)
    return {"tree": parse_tree(text)}


@router.get("/repo/file")
async def repo_file(request: Request, path: str, start: int = 1, end: int = 200) -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "repo__read_code", {"path": path, "start_line": start, "end_line": end})
    if not ok:
        raise HTTPException(400, text)
    return {"path": path, "content": text}


@router.get("/repo/search")
async def repo_search(request: Request, pattern: str, glob: str = "*") -> dict[str, Any]:
    ok, text = await read_tool(studio(request), "repo__search_code", {"pattern": pattern[:200], "glob": glob[:50]})
    if not ok:
        raise HTTPException(400, text)
    return {"pattern": pattern, "hits": parse_search_hits(text)}
