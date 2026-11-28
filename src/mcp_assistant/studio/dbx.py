"""Database Explorer backend.

It reuses the *same* read-only SQLAlchemy engine and SQL guard as the `db` MCP server
(`servers.db_server._engine(True)`, `security.assert_read_only`), so there is exactly one definition of
"read-only". There is deliberately no write path here: INSERT/UPDATE exist only as the `db__execute_write`
MCP tool, which goes through the permission policy and human approval.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, String, Table, and_, cast, func, inspect, or_, select, text
from sqlalchemy.engine import Engine, make_url

from .. import config
from ..security import assert_read_only, redact_secrets

_SENSITIVE_COL = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|cookie|ssn|card_?number)")
MASK = "••••••"
MAX_PAGE = 200
MAX_SQL_ROWS = 1000
QUERY_TIMEOUT_S = 10
FILTER_OPS = {"eq", "ne", "contains", "startswith", "gt", "gte", "lt", "lte", "null", "notnull"}


def jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v)


class DatabaseExplorer:
    def __init__(self, history_path: Path) -> None:
        self.history_path = history_path
        self.last_ok: str | None = None
        self.last_error: str | None = None

    # ---------------------------------------------------------------- plumbing
    @property
    def engine(self) -> Engine:
        # Imported lazily: db_server reads DATABASE_URL at import time, which must happen *after* .env is loaded.
        from ..servers import db_server

        return db_server._engine(True)  # read-only engine shared with the MCP db server

    def _safe_error(self, exc: Exception) -> str:
        msg = redact_secrets(f"{type(exc).__name__}: {exc}")
        return re.sub(r"(?i)(password|pwd)=\S+", r"\1=[REDACTED]", msg)[:500]

    def _row_mask(self, columns: list[str]) -> set[int]:
        return {i for i, c in enumerate(columns) if _SENSITIVE_COL.search(c)}

    def _clean_rows(self, columns: list[str], rows: list[Any]) -> list[list[Any]]:
        masked = self._row_mask(columns)
        out = []
        for r in rows:
            out.append([MASK if i in masked and v is not None else (redact_secrets(v) if isinstance(v, str) else jsonable(v))
                        for i, v in enumerate(r)])
        return out

    # ---------------------------------------------------------------- overview
    def info(self) -> dict[str, Any]:
        url = make_url(config.db_url())
        dialect = url.get_backend_name()
        label = Path(url.database or "").name if dialect == "sqlite" else (url.database or "")
        base = {"dialect": dialect, "database": label, "read_only": True, "last_successful_query": self.last_ok,
                "connection": "unknown", "error": None, "table_count": None, "total_rows": None}
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            insp = inspect(self.engine)
            names = insp.get_table_names()
            base.update(connection="connected", table_count=len(names))
            total = 0
            with self.engine.connect() as conn:
                for n in names:
                    total += conn.execute(select(func.count()).select_from(self._table(n))).scalar() or 0
            base["total_rows"] = total
        except Exception as exc:
            base.update(connection="error", error=self._safe_error(exc))
        return base

    def _table(self, name: str) -> Table:
        insp = inspect(self.engine)
        if name not in insp.get_table_names():
            raise KeyError(name)
        return Table(name, MetaData(), autoload_with=self.engine)

    # ---------------------------------------------------------------- tables / schema
    def tables(self) -> list[dict[str, Any]]:
        insp = inspect(self.engine)
        out = []
        with self.engine.connect() as conn:
            for name in sorted(insp.get_table_names()):
                t = self._table(name)
                rows = conn.execute(select(func.count()).select_from(t)).scalar() or 0
                out.append({"name": name, "rows": rows, "columns": len(t.columns),
                            "primary_key": [c.name for c in t.primary_key.columns],
                            "foreign_keys": len(insp.get_foreign_keys(name))})
        return out

    def schema(self, table: str) -> dict[str, Any]:
        insp = inspect(self.engine)
        t = self._table(table)
        pk = {c.name for c in t.primary_key.columns}
        fks = insp.get_foreign_keys(table)
        fk_by_col = {}
        for fk in fks:
            for col, ref in zip(fk["constrained_columns"], fk["referred_columns"]):
                fk_by_col[col] = {"table": fk["referred_table"], "column": ref}
        uniques = {c for u in insp.get_unique_constraints(table) for c in u["column_names"]}
        columns = [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True)), "primary_key": c["name"] in pk,
                    "unique": c["name"] in uniques, "default": None if c.get("default") is None else str(c["default"]),
                    "foreign_key": fk_by_col.get(c["name"]), "sensitive": bool(_SENSITIVE_COL.search(c["name"]))}
                   for c in insp.get_columns(table)]
        referenced_by = []
        for other in insp.get_table_names():
            for fk in insp.get_foreign_keys(other):
                if fk["referred_table"] == table:
                    referenced_by.append({"table": other, "columns": fk["constrained_columns"], "ref_columns": fk["referred_columns"]})
        with self.engine.connect() as conn:
            rows = conn.execute(select(func.count()).select_from(t)).scalar() or 0
        return {"name": table, "rows": rows, "columns": columns, "primary_key": sorted(pk),
                "foreign_keys": [{"columns": f["constrained_columns"], "ref_table": f["referred_table"], "ref_columns": f["referred_columns"]} for f in fks],
                "indexes": [{"name": i.get("name"), "columns": i["column_names"], "unique": bool(i.get("unique"))} for i in insp.get_indexes(table)],
                "referenced_by": referenced_by}

    def relations(self) -> dict[str, Any]:
        insp = inspect(self.engine)
        nodes, edges = [], []
        for name in sorted(insp.get_table_names()):
            pk = set(insp.get_pk_constraint(name).get("constrained_columns") or [])
            fk_cols = {c for fk in insp.get_foreign_keys(name) for c in fk["constrained_columns"]}
            nodes.append({"id": name, "columns": [{"name": c["name"], "type": str(c["type"]), "pk": c["name"] in pk, "fk": c["name"] in fk_cols}
                                                   for c in insp.get_columns(name)]})
            for fk in insp.get_foreign_keys(name):
                edges.append({"from": name, "to": fk["referred_table"], "columns": fk["constrained_columns"], "ref_columns": fk["referred_columns"]})
        return {"nodes": nodes, "edges": edges}

    # ---------------------------------------------------------------- data browser
    def browse(self, table: str, page: int = 1, page_size: int = 25, sort: str | None = None, order: str = "asc",
               search: str = "", filters: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        t = self._table(table)
        page, page_size = max(1, page), max(1, min(page_size, MAX_PAGE))
        cols = {c.name: c for c in t.columns}
        conds = []
        if search.strip():
            like = f"%{search.strip()}%"
            conds.append(or_(*[cast(c, String).ilike(like) for c in t.columns if not _SENSITIVE_COL.search(c.name)]))
        for f in filters or []:
            col, op, val = cols.get(f.get("column", "")), f.get("op"), f.get("value")
            if col is None or op not in FILTER_OPS:
                raise ValueError(f"Invalid filter: {f}")
            conds.append({
                "eq": lambda: col == val, "ne": lambda: col != val, "gt": lambda: col > val, "gte": lambda: col >= val,
                "lt": lambda: col < val, "lte": lambda: col <= val, "null": lambda: col.is_(None), "notnull": lambda: col.is_not(None),
                "contains": lambda: cast(col, String).ilike(f"%{val}%"), "startswith": lambda: cast(col, String).ilike(f"{val}%"),
            }[op]())
        where = and_(*conds) if conds else None
        q = select(t)
        count_q = select(func.count()).select_from(t)
        if where is not None:
            q, count_q = q.where(where), count_q.where(where)
        if sort:
            if sort not in cols:
                raise ValueError(f"Unknown sort column '{sort}'.")
            q = q.order_by(cols[sort].desc() if order == "desc" else cols[sort].asc())
        else:
            pk = list(t.primary_key.columns)
            if pk:
                q = q.order_by(*pk)
        q = q.limit(page_size).offset((page - 1) * page_size)
        with self.engine.connect() as conn:
            total = conn.execute(count_q).scalar() or 0
            result = conn.execute(q)
            columns = list(result.keys())
            rows = [tuple(r) for r in result.fetchall()]
        self.last_ok = _now()
        return {"table": table, "columns": columns, "rows": self._clean_rows(columns, rows), "page": page, "page_size": page_size,
                "total": total, "pages": max(1, -(-total // page_size)), "ms": round((time.perf_counter() - t0) * 1000, 1),
                "masked_columns": [c for c in columns if _SENSITIVE_COL.search(c)]}

    # ---------------------------------------------------------------- SQL workspace
    def run_sql(self, sql: str, max_rows: int = 200) -> dict[str, Any]:
        max_rows = max(1, min(max_rows, MAX_SQL_ROWS))
        t0 = time.perf_counter()
        try:
            cleaned = assert_read_only(sql)  # raises ValueError for anything but one SELECT/WITH/EXPLAIN
            eng = self.engine
            with eng.connect() as conn:
                if eng.dialect.name == "postgresql":
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                if eng.dialect.name == "sqlite":
                    raw = conn.connection.driver_connection
                    deadline = time.time() + QUERY_TIMEOUT_S
                    raw.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)  # abort runaway queries
                result = conn.execute(text(cleaned))
                columns = list(result.keys())
                rows = [tuple(r) for r in result.fetchmany(max_rows + 1)]
            truncated = len(rows) > max_rows
            payload = {"ok": True, "columns": columns, "rows": self._clean_rows(columns, rows[:max_rows]), "row_count": min(len(rows), max_rows),
                       "truncated": truncated, "ms": round((time.perf_counter() - t0) * 1000, 1), "error": None,
                       "masked_columns": [c for c in columns if _SENSITIVE_COL.search(c)]}
            self.last_ok = _now()
        except Exception as exc:
            msg = self._safe_error(exc)
            if "interrupted" in msg.lower():
                msg = f"Query stopped after {QUERY_TIMEOUT_S}s (time limit)."
            self.last_error = msg
            payload = {"ok": False, "columns": [], "rows": [], "row_count": 0, "truncated": False,
                       "ms": round((time.perf_counter() - t0) * 1000, 1), "error": msg, "masked_columns": []}
        self._remember(sql, payload)
        return payload

    # ---------------------------------------------------------------- history
    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8"))[:limit]
        except (OSError, json.JSONDecodeError):
            return []

    def _remember(self, sql: str, payload: dict[str, Any]) -> None:
        items = self.history(100)
        items.insert(0, {"ts": _now(), "sql": sql[:2000], "ok": payload["ok"], "ms": payload["ms"], "rows": payload["row_count"], "error": payload["error"]})
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(items[:100], ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
