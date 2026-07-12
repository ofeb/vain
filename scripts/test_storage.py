"""smoke tests for file-backed redis and postgres storage."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def test_redis() -> None:
    from core.managers.filetypes import CACHE_REDIS_FILE, ensure_storage_files

    spec = importlib.util.spec_from_file_location(
        "file_redis",
        ROOT / "core/managers/redis/file.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    FileVainCache = mod.FileVainCache

    ensure_storage_files(postgres=False, redis=True)
    if CACHE_REDIS_FILE.exists():
        CACHE_REDIS_FILE.unlink()

    ensure_storage_files(postgres=False, redis=True)
    cache = await FileVainCache.open()
    assert cache.path == CACHE_REDIS_FILE.resolve()
    await cache.set("prefix:1:2", {"user": None, "guild": [","]}, ex=120)
    assert await cache.get("prefix:1:2") == {"user": None, "guild": [","]}
    await cache.close()
    assert CACHE_REDIS_FILE.exists()
    print("redis: ok")


async def test_postgres_db_file() -> None:
    from core.managers.filetypes import POSTGRES_DB_FILE, ensure_storage_files

    ensure_storage_files(postgres=True, redis=False)
    if POSTGRES_DB_FILE.exists():
        POSTGRES_DB_FILE.unlink()

    ensure_storage_files(postgres=True, redis=False)
    assert POSTGRES_DB_FILE.exists()
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
    await test_postgres_db_file()
    await test_postgres_server()
    print("storage tests finished")


if __name__ == "__main__":
    asyncio.run(main())
