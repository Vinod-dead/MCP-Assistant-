"""Append-only JSONL audit log: every tool decision and call is recorded."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path, session_id: str | None = None) -> None:
        self.path = path
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "session": self.session_id,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def tail(self, n: int = 10) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]


def now() -> float:
    return time.perf_counter()
