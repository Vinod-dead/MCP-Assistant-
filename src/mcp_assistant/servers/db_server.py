"""Databases MCP server -- SQLite out of the box; PostgreSQL / MySQL through DATABASE_URL.

Read queries run on a read-only connection AND pass a SQL guard. For PostgreSQL/MySQL you
should additionally point DATABASE_URL at a database user that only has SELECT rights.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from .. import config
from ..demo_data import ensure_demo_data
from ..security import assert_read_only
from ._common import READ, WRITE, make_server

URL = config.db_url()
IS_SQLITE = URL.startswith("sqlite")
if IS_SQLITE and not os.environ.get("DATABASE_URL"):
    ensure_demo_data(config.data_dir())

mcp = make_server("db", "Query and inspect the business database. Explore the schema before writing SQL.")
_engines: dict[str, Engine] = {}


def _engine(readonly: bool) -> Engine:
    key = "ro" if readonly else "rw"
    if key not in _engines:
        if IS_SQLITE:
            db_file = Path(make_url(URL).database or "").resolve()
            if readonly:
                uri = db_file.as_uri() + "?mode=ro"
                _engines[key] = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
            else:
                _engines[key] = create_engine(URL)
        else:
            _engines[key] = create_engine(URL, pool_pre_ping=True)
    return _engines[key]


def _format(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    lines = [" | ".join(columns)]
    lines += [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    if truncated:
        lines.append("…[more rows not shown; refine the query or raise max_rows]")
    return "\n".join(lines) if rows else "(0 rows)  columns: " + ", ".join(columns)


@mcp.tool(annotations=READ)
def list_tables() -> str:
    """List all tables in the database with their row counts."""
    eng = _engine(True)
    out = []
    with eng.connect() as conn:
        for name in inspect(eng).get_table_names():
            n = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            out.append(f"{name}  ({n} rows)")
    return "\n".join(out) or "(no tables)"


@mcp.tool(annotations=READ)
def describe_table(table: str) -> str:
    """Show the columns, types and foreign keys of a table."""
    insp = inspect(_engine(True))
    if table not in insp.get_table_names():
        raise ValueError(f"Unknown table '{table}'. Use list_tables first.")
    cols = [f"{c['name']} {c['type']}{'' if c.get('nullable', True) else ' NOT NULL'}" for c in insp.get_columns(table)]
    fks = [f"{','.join(fk['constrained_columns'])} -> {fk['referred_table']}({','.join(fk['referred_columns'])})" for fk in insp.get_foreign_keys(table)]
    return f"Table {table}\nColumns:\n  " + "\n  ".join(cols) + (("\nForeign keys:\n  " + "\n  ".join(fks)) if fks else "")


@mcp.tool(annotations=READ)
def query(sql: str, max_rows: int = 50) -> str:
    """Run ONE read-only SQL statement (SELECT/WITH/EXPLAIN) and return the rows as a table."""
    cleaned = assert_read_only(sql)
    max_rows = max(1, min(max_rows, 500))
    eng = _engine(True)
    with eng.connect() as conn:
        if eng.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        result = conn.execute(text(cleaned))
        columns = list(result.keys())
        rows = [tuple(r) for r in result.fetchmany(max_rows + 1)]
    return _format(columns, rows[:max_rows], len(rows) > max_rows)


@mcp.tool(annotations=WRITE)
def execute_write(sql: str) -> str:
    """Run ONE INSERT or UPDATE statement (UPDATE must have a WHERE clause). DELETE/DDL are not allowed."""
    import re

    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if ";" in stripped:
        raise ValueError("Only a single statement is allowed.")
    kind = (stripped.split(None, 1) or [""])[0].lower()
    if kind not in {"insert", "update"}:
        raise ValueError("Only INSERT and UPDATE statements are allowed.")
    if kind == "update" and not re.search(r"\bwhere\b", stripped, re.I):
        raise ValueError("UPDATE must include a WHERE clause.")
    if re.search(r"\b(drop|alter|truncate|attach|pragma|delete)\b", stripped, re.I):
        raise ValueError("Statement contains a forbidden keyword.")
    with _engine(False).begin() as conn:
        res = conn.execute(text(stripped))
    return f"OK: {res.rowcount} row(s) affected."


if __name__ == "__main__":
    mcp.run()
