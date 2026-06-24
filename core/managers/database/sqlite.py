"""local postgres.db file backend (sqlite) when database.enabled is false."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from logging import getLogger
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from ..storage_paths import POSTGRES_DB_FILE

log = getLogger(__name__)


def _resolve_path(path: Path | None = None) -> Path:
    if path is not None and Path(path).name != "postgres.db":
        raise ValueError("database storage file must be named postgres.db")
    POSTGRES_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not POSTGRES_DB_FILE.exists():
        POSTGRES_DB_FILE.touch()
    return POSTGRES_DB_FILE


class SQLiteRow(dict):
    def __getitem__(self, key: Any) -> Any:
        return super().__getitem__(key)

    def __getattr__(self, name: str) -> Any:
        return self[name]

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, default)


class _SQLiteTxn:
    async def __aenter__(self) -> "_SQLiteTxn":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class SQLiteConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def transaction(self) -> _SQLiteTxn:
        return _SQLiteTxn()

    async def fetch(self, sql: str, *args: Any) -> list[SQLiteRow]:
        return await asyncio.to_thread(self._fetch_sync, sql, args)

    async def fetchrow(self, sql: str, *args: Any) -> Optional[SQLiteRow]:
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        row = await self.fetchrow(sql, *args)
        if row is None:
            return None
        return next(iter(row.values()))

    async def executemany(self, sql: str, args: Iterable[Sequence]) -> None:
        await asyncio.to_thread(self._executemany_sync, sql, list(args))

    def _fetch_sync(self, sql: str, args: tuple[Any, ...]) -> list[SQLiteRow]:
        sql = adapt_sql(sql)
        args = adapt_args(args)
        cur = self._conn.execute(sql, args)
        if cur.description is None:
            self._conn.commit()
            return []
        cols = [col[0] for col in cur.description]
        return [SQLiteRow(dict(zip(cols, row))) for row in cur.fetchall()]

    def _executemany_sync(self, sql: str, args: list[Sequence]) -> None:
        sql = adapt_sql(sql)
        self._conn.executemany(sql, [adapt_args(tuple(row)) for row in args])
        self._conn.commit()


class _PoolConn:
    def __init__(self, pool: "SQLitePool") -> None:
        self._pool = pool

    async def __aenter__(self) -> SQLiteConnection:
        await self._pool._lock.acquire()
        return self._pool._connection

    async def __aexit__(self, *_: Any) -> None:
        self._pool._lock.release()


class SQLitePool:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._connection: SQLiteConnection

    @classmethod
    async def open(cls, path: Path | None = None) -> "SQLitePool":
        path = _resolve_path(path)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        inst = cls(path)
        inst._connection = SQLiteConnection(conn)
        log.info("postgres.db ready at %s", path)
        return inst

    def acquire(self) -> _PoolConn:
        return _PoolConn(self)

    async def close(self) -> None:
        await asyncio.to_thread(self._connection._conn.close)


def adapt_args(args: tuple[Any, ...]) -> tuple[Any, ...]:
    out: list[Any] = []
    for value in args:
        if isinstance(value, (dict, list, tuple)) and not isinstance(value, str):
            import json

            out.append(json.dumps(value))
        else:
            out.append(value)
    return tuple(out)


def adapt_sql(sql: str) -> str:
    sql = re.sub(r"\broleplay\.(\w+)", r"roleplay_\1", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\$\d+", "?", sql)
    sql = re.sub(r"\bTRUE\b", "1", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bFALSE\b", "0", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bBIGINT\b", "INTEGER", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bBOOLEAN\b", "INTEGER", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bSERIAL\b", "INTEGER", sql, flags=re.IGNORECASE)
    sql = re.sub(r"TIMESTAMPTZ\b", "TEXT", sql, flags=re.IGNORECASE)
    sql = re.sub(r"TIMESTAMP\b", "TEXT", sql, flags=re.IGNORECASE)
    sql = re.sub(r"JSONB\b", "TEXT", sql, flags=re.IGNORECASE)
    sql = re.sub(r"TEXT\[\]", "TEXT", sql, flags=re.IGNORECASE)
    return sql


def postgres_schema_to_sqlite(schema: str) -> str:
    skip_prefixes = (
        "CREATE EXTENSION",
        "CREATE SCHEMA",
        "SELECT create_hypertable",
        "timescaledb",
    )
    lines: list[str] = []
    for raw in schema.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            continue
        upper = stripped.upper()
        if any(token in upper for token in skip_prefixes):
            continue
        if upper.startswith("CREATE INDEX") and "USING GIN" in upper:
            continue
        line = raw
        line = re.sub(r"\bTEXT\[\]", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\bBIGINT\[\]", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\bINTEGER\[\]", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(
            r"DEFAULT\s+ARRAY\[[^\]]*\](::[A-Z\[\]]+)?",
            "DEFAULT '[]'",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(r"ARRAY\[[^\]]*\](::[A-Z\[\]]+)?", "'[]'", line, flags=re.IGNORECASE)
        line = re.sub(r"\bGENERATED ALWAYS AS IDENTITY\b", "", line, flags=re.IGNORECASE)
        lines.append(adapt_sql(line))
    return "\n".join(lines)


async def apply_schema(path: Path, schema_sql: str) -> None:
    converted = postgres_schema_to_sqlite(schema_sql)
    statements = [stmt.strip() for stmt in converted.split(";") if stmt.strip()]

    def _run() -> None:
        conn = sqlite3.connect(path, check_same_thread=False)
        try:
            for stmt in statements:
                try:
                    conn.execute(stmt)
                except sqlite3.Error as exc:
                    log.debug("skip schema statement (%s): %s", exc, stmt[:120])
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_run)
