"""postgres database connection pool.
wraps asyncpg with basic caching built in.
use fetch fetchrow fetchval or execute"""

from __future__ import annotations
import asyncio, glob, json
from logging import getLogger
from types import TracebackType
from typing import Any, Iterable, Optional, Protocol, Sequence, Union
import ujson
from asyncpg import Connection, Pool, Record as BaseRecord, create_pool
from discord.ext.commands import Context, check
from ..values import database

log = getLogger(__name__)


def query_limit(table: str, limit: int = 5):
    """check row count before insert"""
    async def predicate(ctx: Context):
        count = await ctx.bot.db.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE guild_id = $1", ctx.guild.id
        )
        if count == limit:
            await ctx.fail(f"cant make more than **{limit}** {table}s")
            return False
        return True
    return check(predicate)


class Row(BaseRecord):
    """asyncpg record with attr access"""
    def __getattr__(self, name: Union[str, Any]) -> Any:
        return self[name]

    def __dict__(self) -> dict:
        return dict(self)


class ConnProto(Protocol):
    """connection context manager type"""
    async def __aenter__(self) -> Connection: ...
    async def __aexit__(self, et, ev, tb) -> None: ...


class Database:
    """postgres pool wrapper with cache"""

    def __init__(self):
        self.uri: str = database.dsn
        self.pool: Optional[Pool] = None
        self.cache: dict = {}

    def _encode(self, *data: Any):
        return ujson.dumps(data[1])

    def _decode(self, *data: Any):
        return ujson.loads(data[1])

    async def _init_conn(self, conn: Connection) -> None:
        await conn.set_type_codec(
            "json",
            encoder=self._encode,
            decoder=self._decode,
            schema="pg_catalog",
        )

    async def _make_pool(self) -> Pool:
        pool = await create_pool(dsn=self.uri, init=self._init_conn, record_class=Row)
        log.info(f"db pool ready {pool.__hash__()}")
        return pool

    def _create_db(self, name: str, user: str, pw: str, host: str, port: int):
        """create db if not exists"""
        import psycopg2
        conn = psycopg2.connect(dbname="postgres", user=user, password=pw, host=host, port=port)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE {name};")
            with open("var/migrations.sql", "r") as f:
                cur.execute(f.read())
        conn.close()

    async def connect(self) -> Pool:
        """open pool, create db if missing"""
        tail = self.uri.replace("postgres://", "")
        auth, rest = tail.split("@")
        user, pw = auth.split(":")
        host_port, name = rest.split("/")
        host, port = host_port.split(":")
        try:
            self.pool = await self._make_pool()
        except Exception:
            await asyncio.to_thread(self._create_db, name, user, pw, host, int(port))
            self.pool = await self._make_pool()
        try:
            await self.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        except Exception as e:
            log.warning(f"timescaledb not available: {e}")
        return self.pool

    async def close(self) -> None:
        """close pool connection"""
        if self.pool:
            await self.pool.close()
            log.info("db pool closed")

    async def _bust(self, key: str) -> None:
        """remove cache entry after delay"""
        await asyncio.sleep(60)
        self.cache.pop(key, None)

    async def _store(self, data: Any, op: str, sql: str, args) -> None:
        if "economy" not in sql.lower():
            self.cache[f"{op} {sql} {args}"] = data

    async def _purge_table(self, table: str) -> None:
        keys = [k for k in self.cache if table.lower() in k.lower()]
        for k in keys:
            self.cache.pop(k, None)

    async def fetch(self, sql: str, *args, **kw) -> list:
        """fetch all rows"""
        key = f"fetch {sql} {args}"
        if kw.get("cached", True) and (hit := self.cache.get(key)):
            return hit
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await conn.fetch(sql, *args)
                await self._store(data, "fetch", sql, args)
                return data

    async def fetchiter(self, sql: str, *args):
        """yield rows one by one"""
        for row in await self.fetch(sql, *args):
            yield row

    async def fetchrow(self, sql: str, *args, **kw) -> Optional[Row]:
        """fetch single row"""
        key = f"fetchrow {sql} {args}"
        if kw.get("cached", True) and (hit := self.cache.get(key)):
            return hit
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await conn.fetchrow(sql, *args)
                await self._store(data, "fetchrow", sql, args)
                return data

    async def fetchval(self, sql: str, *args, **kw) -> Any:
        """fetch single value"""
        key = f"fetchval {sql} {args}"
        if kw.get("cached", True) and (hit := self.cache.get(key)):
            return hit
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await conn.fetchval(sql, *args)
                await self._store(data, "fetchval", sql, args)
                return data

    async def execute(self, sql: str, *args, **kw) -> Any:
        """run a write query"""
        args = [json.dumps(a) if isinstance(a, dict) else a for a in args]
        try:
            table = sql.lower().split("from")[1].split("where")[0].strip()
            await self._purge_table(table)
        except Exception:
            pass
        try:
            if sql.lower().startswith("update"):
                table = sql.lower().split("update")[1].split("set")[0].strip()
                await self._purge_table(table)
        except Exception:
            pass
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.fetchval(sql, *args)

    async def executemany(self, sql: str, args: Iterable[Sequence]) -> Any:
        """run query with multiple arg sets"""
        self.cache.pop(f"{sql} {args}", None)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.executemany(sql, args)

    async def migrate(self) -> Optional[bool]:
        """run pending sql migration files"""
        if await self.fetchval("SELECT count(*) FROM pokemon.users") > 10:
            log.info("no migrations needed")
            return
        files = sorted(
            glob.glob("var/migration_*.sql"),
            key=lambda x: int(x.split("_")[-1].split(".")[0]),
        )
        combined = "".join(open(f).read() for f in files)
        with open("var/migrations.sql", "w") as f:
            f.write(combined)
        return True

    async def purge(self, column: str, value: Any) -> None:
        """delete value from all matching tables"""
        tables = [
            r.table_name
            for r in await self.fetch(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = $1",
                column,
            )
        ]
        await asyncio.gather(*[
            self.execute(f"DELETE FROM {t} WHERE {column} = $1", value)
            for t in tables
        ])
