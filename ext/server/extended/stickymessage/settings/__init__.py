from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.server.extended.stickymessage.settings")

class Settings:
    """All `sticky_message` rows for one guild (channel_id, code, limits, interval)."""

    bot: Vain
    guild: Guild
    rows: list[dict[str, Any]]

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.rows = list(rows or [])

    def __bool__(self) -> bool:
        return bool(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        rows = await bot.db.fetch(
            "SELECT * FROM sticky_message WHERE guild_id = $1",
            guild.id,
        )
        return cls(bot, guild, [dict(r) for r in rows])

    @classmethod
    async def fetch_all(cls, bot: Vain, guild: Guild) -> list[dict[str, Any]]:
        settings = await cls.fetch(bot, guild)
        return settings.rows

    async def reload(self) -> Settings:
        fresh = await Settings.fetch(self.bot, self.guild)
        self.rows = fresh.rows
        return self

    async def add(self, **fields: Any) -> dict[str, Any]:
        """Insert a row. Pass columns for `sticky_message` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO sticky_message (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add sticky_message guild=%s fields=%s", self.guild.id, list(fields))
        return data

    async def remove_where(self, **match: Any) -> int:
        """Delete rows matching column equality filters (and this guild)."""
        if not match:
            raise ValueError("remove_where requires filters")
        clauses = ["guild_id = $1"]
        values: list[Any] = [self.guild.id]
        for i, (k, v) in enumerate(match.items(), start=2):
            clauses.append("%s = $%d" % (k, i))
            values.append(v)
        where = " AND ".join(clauses)
        result = await self.bot.db.execute(
            "DELETE FROM sticky_message WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM sticky_message WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear sticky_message guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self

    @staticmethod
    async def ensure_schema(bot: Vain) -> None:
        statements = [
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS message_limit INT NOT NULL DEFAULT 1",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS interval_seconds INT NOT NULL DEFAULT 0",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS message_count INT NOT NULL DEFAULT 0",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS last_sent TIMESTAMP",
        ]
        for sql in statements:
            with contextlib.suppress(Exception):
                await bot.db.execute(sql)

    async def get_row(
        self, guild_id: int, channel_id: int,
        message_limit_default: int, interval_disabled: int,
    ) -> dict | None:
        row = await self.bot.db.fetchrow(
            """SELECT guild_id, channel_id, code, last_message,
                      COALESCE(message_limit, $3) AS message_limit,
                      COALESCE(interval_seconds, $4) AS interval_seconds,
                      COALESCE(message_count, 0) AS message_count,
                      last_sent
               FROM sticky_message
               WHERE guild_id = $1 AND channel_id = $2""",
            guild_id,
            channel_id,
            message_limit_default,
            interval_disabled,
        )
        return dict(row) if row else None

    async def update_repost(
        self,
        last_message_id: int,
        now,
        guild_id: int,
        channel_id: int,
    ) -> None:
        await self.bot.db.execute(
            """UPDATE sticky_message
               SET last_message = $1, message_count = 0, last_sent = $2
               WHERE guild_id = $3 AND channel_id = $4""",
            last_message_id,
            now,
            guild_id,
            channel_id,
        )

    async def upsert_sticky(
        self,
        guild_id: int,
        channel_id: int,
        code: str,
        message_limit: int,
        interval_seconds: int,
        now,
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO sticky_message
                   (guild_id, channel_id, code, message_limit, interval_seconds, message_count, last_sent)
               VALUES ($1, $2, $3, $4, $5, 0, $6)
               ON CONFLICT (guild_id, channel_id) DO UPDATE SET
                   code = excluded.code,
                   message_limit = excluded.message_limit,
                   interval_seconds = excluded.interval_seconds,
                   message_count = 0,
                   last_sent = excluded.last_sent""",
            guild_id,
            channel_id,
            code,
            message_limit,
            interval_seconds,
            now,
        )

    async def update_sticky(
        self,
        code: str,
        message_limit: int,
        interval_seconds: int,
        now,
        guild_id: int,
        channel_id: int,
    ) -> None:
        await self.bot.db.execute(
            """UPDATE sticky_message
               SET code = $1, message_limit = $2, interval_seconds = $3,
                   message_count = 0, last_sent = $4
               WHERE guild_id = $5 AND channel_id = $6""",
            code,
            message_limit,
            interval_seconds,
            now,
            guild_id,
            channel_id,
        )

    async def update_interval(
        self, seconds: int, guild_id: int, channel_id: int
    ) -> None:
        await self.bot.db.execute(
            "UPDATE sticky_message SET interval_seconds = $1 WHERE guild_id = $2 AND channel_id = $3",
            seconds,
            guild_id,
            channel_id,
        )

    async def update_message_limit(
        self,
        limit: int,
        interval: int,
        guild_id: int,
        channel_id: int,
    ) -> None:
        await self.bot.db.execute(
            """UPDATE sticky_message
               SET message_limit = $1, interval_seconds = $2, message_count = 0
               WHERE guild_id = $3 AND channel_id = $4""",
            limit,
            interval,
            guild_id,
            channel_id,
        )

    async def fetch_all_entries(
        self,
        guild_id: int,
        message_limit_default: int,
        interval_disabled: int,
    ) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetch(
            """SELECT channel_id, code,
                      COALESCE(message_limit, $2) AS message_limit,
                      COALESCE(interval_seconds, $3) AS interval_seconds
               FROM sticky_message WHERE guild_id = $1""",
            guild_id,
            message_limit_default,
            interval_disabled,
        )
        return [dict(r) for r in rows]

    async def delete_sticky(self, guild_id: int, channel_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM sticky_message WHERE guild_id = $1 AND channel_id = $2",
            guild_id,
            channel_id,
        )

    async def update_script(
        self, code: str, guild_id: int, channel_id: int
    ) -> None:
        await self.bot.db.execute(
            "UPDATE sticky_message SET code = $1 WHERE guild_id = $2 AND channel_id = $3",
            code,
            guild_id,
            channel_id,
        )

    async def update_message_count(
        self, count: int, guild_id: int, channel_id: int
    ) -> None:
        await self.bot.db.execute(
            "UPDATE sticky_message SET message_count = $1 WHERE guild_id = $2 AND channel_id = $3",
            count,
            guild_id,
            channel_id,
        )

    async def fetch_interval_rows(self) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetch(
            """SELECT guild_id, channel_id, code,
                      COALESCE(interval_seconds, 0) AS interval_seconds,
                      COALESCE(message_count, 0) AS message_count,
                      COALESCE(message_limit, 1) AS message_limit,
                      last_sent
               FROM sticky_message
               WHERE COALESCE(interval_seconds, 0) >= 30
                 AND COALESCE(message_limit, 1) > 1"""
        )
        return [dict(r) for r in rows]

async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)

async def fetch_all(bot: Vain, guild: Guild) -> list[dict[str, Any]]:
    return await Settings.fetch_all(bot, guild)

async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)

async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.insert(**kwargs)

__all__ = ["Settings", "fetch", "fetch_all", "upsert", "insert"]
