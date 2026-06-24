"""smoke tests for file-backed redis and postgres."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def test_redis() -> None:
    from core.managers.storage_paths import CACHE_REDIS_FILE, ensure_storage_files

    spec = importlib.util.spec_from_file_location(
        "file_redis",
        ROOT / "core/managers/redis/file.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    FileBleedCache = mod.FileBleedCache

    ensure_storage_files(postgres=False, redis=True)
    if CACHE_REDIS_FILE.exists():
        CACHE_REDIS_FILE.unlink()

    ensure_storage_files(postgres=False, redis=True)
    cache = await FileBleedCache.open()
    assert cache.path == CACHE_REDIS_FILE.resolve()
    await cache.set("prefix:1:2", {"user": None, "guild": [","]}, ex=120)
    assert await cache.get("prefix:1:2") == {"user": None, "guild": [","]}
    await cache.close()
    assert CACHE_REDIS_FILE.exists()
    print("redis: ok")


async def test_postgres_file() -> None:
    from core.managers.database.sqlite import SQLitePool, apply_schema, adapt_sql
    from core.managers.storage_paths import POSTGRES_DB_FILE, ensure_storage_files

    ensure_storage_files(postgres=True, redis=False)
    if POSTGRES_DB_FILE.exists():
        POSTGRES_DB_FILE.unlink()

    ensure_storage_files(postgres=True, redis=False)
    assert POSTGRES_DB_FILE.exists()

    schema = (ROOT / "core/managers/database/models/schema.sql").read_text(encoding="utf-8")
    await apply_schema(POSTGRES_DB_FILE, schema)
    pool = await SQLitePool.open(POSTGRES_DB_FILE)

    sql = adapt_sql(
        """
        INSERT INTO roleplay.actions (action, giver, receiver, amount)
            VALUES ($1, $2, $3, 1)
        ON CONFLICT (action, giver, receiver)
            DO UPDATE SET amount = roleplay.actions.amount + 1
        RETURNING amount
        """
    )
    async with pool.acquire() as conn:
        amount = await conn.fetchval(sql, "hug", 1, 2)
        assert amount == 1
    await pool.close()
    print("postgres.db: ok")


async def test_postgres_server() -> None:
    from core.managers.values import database

    if not database.enabled:
        print("postgres server: skipped (database.enabled is false)")
        return

    try:
        import asyncpg
    except ImportError:
        print("postgres server: skipped (asyncpg not installed)")
        return

    try:
        conn = await asyncpg.connect(database.dsn, timeout=5)
    except Exception as exc:
        print(f"postgres server: skipped ({exc})")
        return

    await conn.close()
    print("postgres server: ok")


async def main() -> None:
    await test_redis()
    await test_postgres_file()
    await test_postgres_server()
    print("storage tests finished")


if __name__ == "__main__":
    asyncio.run(main())
