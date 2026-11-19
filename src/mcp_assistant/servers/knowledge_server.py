"""Knowledge MCP server -- hybrid RAG (BM25 + Gemini embeddings, RRF fusion) over your documents."""
from __future__ import annotations

from .. import config
from ..docs import extract_text, is_supported
from ..retrieval import KnowledgeIndex, default_embedder
from ._common import READ, WRITE, assert_not_secret, make_server, resolve_in_root, truncate

ROOT = config.files_root()
INDEX_PATH = config.data_dir() / "knowledge" / "index.json"
mcp = make_server(
    "knowledge",
    "Semantic + keyword search over the user's indexed documents. Index a folder first, then search. Cite sources.",
)


@mcp.tool(annotations=WRITE)
def index_folder(path: str = ".") -> str:
    """Index (or re-index) all supported documents in a workspace folder for search. Safe to repeat."""
    base = resolve_in_root(ROOT, path)
    idx = KnowledgeIndex(INDEX_PATH)
    embedder = default_embedder()
    added = skipped = chunks = 0
    for f in sorted(base.rglob("*")):
        if not f.is_file() or f.name.startswith(".") or not is_supported(f):
            continue
        try:
            assert_not_secret(f)
            rel = f.relative_to(ROOT).as_posix()
            mtime = f.stat().st_mtime
            if idx.files.get(rel) == mtime:
                skipped += 1
                continue
            chunks += idx.add_document(rel, extract_text(f), mtime, embedder)
            added += 1
        except (ValueError, OSError):
            continue
    idx.save()
    mode = "hybrid (keyword + embeddings)" if embedder else "keyword-only (set GEMINI_API_KEY for embeddings)"
    return f"Indexed {added} file(s) / {chunks} chunk(s); {skipped} unchanged. Search mode: {mode}."


@mcp.tool(annotations=READ)
def search_knowledge(query: str, k: int = 5) -> str:
    """Search indexed documents. Returns the most relevant passages with their source file."""
    idx = KnowledgeIndex(INDEX_PATH)
    if not idx.chunks:
        return "The knowledge index is empty. Call index_folder first."
    hits = idx.search(query, k=max(1, min(k, 10)), embedder=default_embedder())
    if not hits:
        return f"No relevant passages found for '{query}'."
    return "\n\n".join(f"[{i}] {h['source']} (score {h['score']}, {h['mode']})\n{truncate(h['text'], 900)}" for i, h in enumerate(hits, 1))


@mcp.tool(annotations=READ)
def knowledge_stats() -> str:
    """Show how many documents and chunks are indexed."""
    idx = KnowledgeIndex(INDEX_PATH)
    vectors = sum(1 for c in idx.chunks if c.get("vec"))
    return f"{len(idx.files)} document(s), {len(idx.chunks)} chunk(s), {vectors} with embeddings."


if __name__ == "__main__":
    mcp.run()
