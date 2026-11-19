"""Persistent long-term memory (facts the assistant should remember about the user/work)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .retrieval import BM25, tokenize


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[dict[str, Any]] = []
        if path.exists():
            self.items = json.loads(path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, fact: str, tags: list[str] | None = None) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:8],
            "fact": fact.strip(),
            "tags": tags or [],
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.items.append(item)
        self._save()
        return item

    def forget(self, memory_id: str) -> bool:
        before = len(self.items)
        self.items = [m for m in self.items if m["id"] != memory_id]
        if len(self.items) != before:
            self._save()
            return True
        return False

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not self.items:
            return []
        q = tokenize(query)
        if not q:
            return self.items[-k:][::-1]
        bm = BM25([tokenize(m["fact"] + " " + " ".join(m["tags"])) for m in self.items])
        scores = bm.scores(q)
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
        return [self.items[i] for i in ranked[:k] if scores[i] > 0]
