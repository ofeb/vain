"""fixed local storage paths under core/storage/."""

from __future__ import annotations

import logging
from pathlib import Path

from .values import storage

log = logging.getLogger("vain.storage")

CACHE_REDIS_FILE: Path = storage / "cache.redis"
POSTGRES_DB_FILE: Path = storage / "postgres.db"

_EMPTY_REDIS = b'{"keys":{}}'

def ensure_storage_dir() -> None:
    storage.mkdir(parents=True, exist_ok=True)


def ensure_storage_files(*, postgres: bool = True, redis: bool = True) -> None:
    """create core/storage and default cache.redis / postgres.db if missing."""
    ensure_storage_dir()

    if redis and not CACHE_REDIS_FILE.exists():
        CACHE_REDIS_FILE.write_bytes(_EMPTY_REDIS)
        log.info("created %s", CACHE_REDIS_FILE)

    if postgres and not POSTGRES_DB_FILE.exists():
        POSTGRES_DB_FILE.touch()
        log.info("created %s", POSTGRES_DB_FILE)
