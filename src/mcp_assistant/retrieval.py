"""Retrieval built from scratch: BM25 + optional dense embeddings, fused with RRF.

* BM25 is implemented here (pure Python, no dependencies).
* Dense vectors are optional (Gemini embeddings); if they are unavailable the index still
  works lexically. Both rankings are merged with Reciprocal Rank Fusion.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Protocol

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an and are as at be by for from has have i in is it of on or that the this to was were will with".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(doc) for doc in corpus]
        self.lengths = [len(doc) for doc in corpus]
        self.avg_len = (sum(self.lengths) / len(corpus)) if corpus else 0.0
        df: Counter[str] = Counter()
        for doc in corpus:
            df.update(set(doc))
        n = len(corpus)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out: list[float] = []
        terms = set(query)
        for tf, length in zip(self.tf, self.lengths):
            score = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    norm = 1 - self.b + self.b * (length / self.avg_len if self.avg_len else 1)
                    score += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * norm)
            out.append(score)
        return out


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Paragraph-aware chunking with a little overlap between neighbouring chunks."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        while len(p) > size:  # hard-split very long paragraphs
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:size])
            p = p[size - overlap :]
        if len(cur) + len(p) + 2 <= size:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            tail = cur[-overlap:] if (cur and overlap) else ""
            cur = f"{tail}\n\n{p}" if tail else p
    if cur:
        chunks.append(cur)
    return chunks


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion over several ranked lists of document indices."""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    def __init__(self, model: str | None = None) -> None:
        from google import genai

        self.model = model or os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
        self.client = genai.Client()

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            resp = self.client.models.embed_content(
                model=self.model,
                contents=texts[i : i + 64],
                config=types.EmbedContentConfig(task_type=task),
            )
            out.extend(list(e.values) for e in resp.embeddings)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


def default_embedder() -> Embedder | None:
    """Gemini embedder if credentials are available, otherwise None (lexical-only)."""
    from .config import have_gemini_credentials

    if os.environ.get("DISABLE_EMBEDDINGS", "").lower() in {"1", "true"} or not have_gemini_credentials():
        return None
    try:
        return GeminiEmbedder()
    except Exception:
        return None


class KnowledgeIndex:
    """A small persistent hybrid (lexical + vector) index stored as JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.chunks: list[dict[str, Any]] = []
        self.files: dict[str, float] = {}
        self._bm25: BM25 | None = None
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.chunks, self.files = data.get("chunks", []), data.get("files", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"chunks": self.chunks, "files": self.files}), encoding="utf-8")

    def add_document(self, source: str, text: str, mtime: float, embedder: Embedder | None = None) -> int:
        self.chunks = [c for c in self.chunks if c["source"] != source]
        pieces = chunk_text(text)
        vectors: list[list[float]] | list[None] = [None] * len(pieces)
        if embedder and pieces:
            try:
                vectors = embedder.embed_documents(pieces)
            except Exception:
                vectors = [None] * len(pieces)
        for i, (piece, vec) in enumerate(zip(pieces, vectors)):
            self.chunks.append({"id": f"{source}#{i}", "source": source, "text": piece, "vec": vec})
        self.files[source] = mtime
        self._bm25 = None
        return len(pieces)

    def search(self, query: str, k: int = 5, embedder: Embedder | None = None) -> list[dict[str, Any]]:
        if not self.chunks:
            return []
        if self._bm25 is None:
            self._bm25 = BM25([tokenize(c["text"]) for c in self.chunks])
        lex = self._bm25.scores(tokenize(query))
        lex_rank = [i for i in sorted(range(len(lex)), key=lambda i: -lex[i]) if lex[i] > 0][:50]

        dense_rank: list[int] = []
        if embedder and any(c.get("vec") for c in self.chunks):
            try:
                qv = embedder.embed_query(query)
                sims = {i: cosine(qv, c["vec"]) for i, c in enumerate(self.chunks) if c.get("vec")}
                dense_rank = sorted(sims, key=lambda i: -sims[i])[:50]
            except Exception:
                dense_rank = []

        rankings = [r for r in (lex_rank, dense_rank) if r]
        if not rankings:
            return []
        mode = "hybrid" if len(rankings) == 2 else ("dense" if dense_rank else "lexical")
        fused = rrf(rankings)[:k]
        return [
            {"source": self.chunks[i]["source"], "chunk": self.chunks[i]["id"], "score": round(s, 4), "mode": mode,
             "text": self.chunks[i]["text"]}
            for i, s in fused
        ]
