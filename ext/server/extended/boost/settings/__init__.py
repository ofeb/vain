from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.server.extended.boost.settings")


class Settings:
    """All `boost_messages` rows for one guild (channel_id, message, self_destruct)."""

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

    @staticmethod
    async def ensure_schema(db) -> None:
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE boost_messages ADD COLUMN IF NOT EXISTS is_second BOOLEAN NOT NULL DEFAULT FALSE"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                """
                DO $$ BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'boost_messages_guild_channel_second_key'
                  ) THEN
                    ALTER TABLE boost_messages
                      DROP CONSTRAINT IF EXISTS boost_messages_pkey;
                    ALTER TABLE boost_messages
                      ADD CONSTRAINT boost_messages_guild_channel_second_key
                      UNIQUE (guild_id, channel_id, is_second);
                  END IF;
                END $$;
                """
            )

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        rows = await bot.db.fetch(
            "SELECT * FROM boost_messages WHERE guild_id = $1",
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
        """Insert a row. Pass columns for `boost_messages` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO boost_messages (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add boost_messages guild=%s fields=%s", self.guild.id, list(fields))
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
            "DELETE FROM boost_messages WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM boost_messages WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear boost_messages guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self

    @staticmethod
    async def exists(
        db, guild_id: int, channel_id: int, is_second: bool
    ) -> bool:
        return bool(
            await db.fetchval(
                """SELECT 1 FROM boost_messages
                   WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3""",
                guild_id,
                channel_id,
                is_second,
            )
        )

    @staticmethod
    async def upsert_message(
        db,
        guild_id: int,
        channel_id: int,
        message: str,
        self_destruct: int | None,
        is_second: bool,
    ) -> None:
        await db.execute(
            """UPDATE boost_messages SET message = $1, self_destruct = $2
               WHERE guild_id = $3 AND channel_id = $4 AND is_second = $5""",
            message,
            self_destruct,
            guild_id,
            channel_id,
            is_second,
        )

    @staticmethod
    async def insert_message(
        db,
        guild_id: int,
        channel_id: int,
        message: str,
        self_destruct: int | None,
        is_second: bool,
    ) -> None:
        await db.execute(
            """INSERT INTO boost_messages
               (guild_id, channel_id, message, self_destruct, is_second)
               VALUES ($1, $2, $3, $4, $5)""",
            guild_id,
            channel_id,
            message,
            self_destruct,
            is_second,
        )

    @staticmethod
    async def remove_message(
        db, guild_id: int, channel_id: int, is_second: bool
    ) -> bool:
        return bool(
            await db.fetchval(
                """DELETE FROM boost_messages
                   WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3
                   RETURNING channel_id""",
                guild_id,
                channel_id,
                is_second,
            )
        )

    @staticmethod
    async def get_message(
        db, guild_id: int, channel_id: int, is_second: bool
    ) -> str | None:
        return await db.fetchval(
            """SELECT message FROM boost_messages
               WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3""",
            guild_id,
            channel_id,
            is_second,
        )

    @staticmethod
    async def get_all(db, guild_id: int) -> list[dict[str, Any]]:
        rows = await db.fetch(
            """SELECT channel_id, is_second FROM boost_messages WHERE guild_id = $1""",
            guild_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def fetch_by_second(
        db, guild_id: int, is_second: bool
    ) -> list[dict[str, Any]]:
        rows = await db.fetch(
            """SELECT * FROM boost_messages
               WHERE guild_id = $1 AND is_second = $2""",
            guild_id,
            is_second,
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
