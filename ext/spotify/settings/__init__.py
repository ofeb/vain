from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict

from core.vain import Vain

logger = getLogger("vain.spotify.settings")


class Record(TypedDict, total=False):
    user_id: int


class Settings:
    """Row in `spotify_tokens` for one user_id."""

    bot: Vain
    key: int
    record: dict[str, Any]

    def __init__(self, bot: Vain, key: int, record: dict[str, Any] | None = None) -> None:
        self.bot = bot
        self.key = int(key)
        self.record = dict(record or {'user_id': self.key})

    def __bool__(self) -> bool:
        return self.record.get('user_id') is not None and len(self.record) > 1

    def get(self, field: str, default: Any = None) -> Any:
        return self.record.get(field, default)

    @classmethod
    async def fetch(cls, bot: Vain, key: int) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM spotify_tokens WHERE user_id = $1",
            int(key),
        )
        return cls(bot, key, dict(row) if row else None)

    async def upsert(self, **kwargs: Any) -> Settings:
        self.record.update(kwargs)
        self.record['user_id'] = self.key
        cols = ['user_id'] + [k for k in kwargs if k != 'user_id']
        values = [self.record.get(c) for c in cols]
        placeholders = ", ".join("$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        updates = ", ".join(
            "%s = EXCLUDED.%s" % (c, c) for c in cols if c != 'user_id'
        )
        if updates:
            query = (
                "INSERT INTO spotify_tokens (%s) VALUES (%s) "
                "ON CONFLICT (user_id) DO UPDATE SET %s RETURNING *"
            ) % (col_sql, placeholders, updates)
        else:
            query = (
                "INSERT INTO spotify_tokens (%s) VALUES (%s) "
                "ON CONFLICT (user_id) DO NOTHING RETURNING *"
            ) % (col_sql, placeholders)
        row = await self.bot.db.fetchrow(query, *values)
        if row:
            self.record = dict(row)
        logger.debug("upsert spotify_tokens user_id=%s", self.key)
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM spotify_tokens WHERE user_id = $1",
            self.key,
        )
        self.record = {'user_id': self.key}


async def fetch(bot: Vain, key: int) -> Settings:
    return await Settings.fetch(bot, key)


async def upsert(bot: Vain, key: int, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, key)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, key: int, **kwargs: Any) -> Settings:
    return await upsert(bot, key, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
