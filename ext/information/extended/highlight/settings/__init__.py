from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.information.extended.highlight.settings")


class Settings:
    """All `highlights` rows for one guild (user_id, word)."""

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
            "SELECT * FROM highlights WHERE guild_id = $1",
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
        """Insert a row. Pass columns for `highlights` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO highlights (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add highlights guild=%s fields=%s", self.guild.id, list(fields))
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
            "DELETE FROM highlights WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear highlights guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self

    @staticmethod
    async def ensure_schema(db: Any) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS highlights (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                keyword TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, keyword)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS highlight_ignores (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                target_type TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, target_id, target_type)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS highlight_config (
                guild_id BIGINT PRIMARY KEY,
                log_type TEXT NOT NULL DEFAULT 'dm',
                log_channel_id BIGINT,
                punishment TEXT NOT NULL DEFAULT 'none',
                timeout_seconds INTEGER,
                delete_after_seconds INTEGER
            )
            """
        )

    @staticmethod
    async def get_config(db: Any, guild_id: int) -> dict:
        row = await db.fetchrow(
            "SELECT * FROM highlight_config WHERE guild_id = $1",
            guild_id,
        )
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "log_type": "dm",
            "log_channel_id": None,
            "punishment": "none",
            "timeout_seconds": None,
            "delete_after_seconds": None,
        }

    @staticmethod
    async def add_highlight(db: Any, guild_id: int, user_id: int, keyword: str) -> None:
        await db.execute(
            "INSERT INTO highlights (guild_id, user_id, keyword) VALUES($1, $2, $3) "
            "ON CONFLICT(guild_id, user_id, keyword) DO NOTHING",
            guild_id,
            user_id,
            keyword,
        )

    @staticmethod
    async def remove_highlight(db: Any, guild_id: int, user_id: int, keyword: str) -> None:
        await db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
            guild_id,
            user_id,
            keyword,
        )

    @staticmethod
    async def fetch_highlights(db: Any, guild_id: int, user_id: int) -> list[dict]:
        rows = await db.fetch(
            "SELECT keyword FROM highlights WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def reset_highlights(db: Any, guild_id: int, user_id: int) -> None:
        await db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    @staticmethod
    async def set_log_type_dm(db: Any, guild_id: int) -> None:
        await db.execute(
            """
            INSERT INTO highlight_config (guild_id, log_type, log_channel_id)
            VALUES ($1, 'dm', NULL)
            ON CONFLICT (guild_id) DO UPDATE
              SET log_type = 'dm', log_channel_id = NULL
            """,
            guild_id,
        )

    @staticmethod
    async def set_log_type_channel(db: Any, guild_id: int, channel_id: int) -> None:
        await db.execute(
            """
            INSERT INTO highlight_config (guild_id, log_type, log_channel_id)
            VALUES ($1, 'channel', $2)
            ON CONFLICT (guild_id) DO UPDATE
              SET log_type = 'channel', log_channel_id = $2
            """,
            guild_id,
            channel_id,
        )

    @staticmethod
    async def set_punishment(
        db: Any,
        guild_id: int,
        punishment: str,
        timeout_seconds: int | None,
        delete_after_seconds: int | None,
    ) -> None:
        await db.execute(
            """
            INSERT INTO highlight_config (
                guild_id, punishment, timeout_seconds, delete_after_seconds
            ) VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id) DO UPDATE SET
                punishment = $2,
                timeout_seconds = $3,
                delete_after_seconds = $4
            """,
            guild_id,
            punishment,
            timeout_seconds,
            delete_after_seconds,
        )

    @staticmethod
    async def add_ignore(
        db: Any, guild_id: int, user_id: int, target_id: int, target_type: str
    ) -> None:
        await db.execute(
            "INSERT INTO highlight_ignores (guild_id, user_id, target_id, target_type) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            guild_id,
            user_id,
            target_id,
            target_type,
        )

    @staticmethod
    async def remove_ignore(
        db: Any, guild_id: int, user_id: int, target_id: int, target_type: str
    ) -> None:
        await db.execute(
            "DELETE FROM highlight_ignores WHERE guild_id = $1 AND user_id = $2 "
            "AND target_id = $3 AND target_type = $4",
            guild_id,
            user_id,
            target_id,
            target_type,
        )

    @staticmethod
    async def fetch_ignores(db: Any, guild_id: int, user_id: int) -> list[dict]:
        rows = await db.fetch(
            "SELECT target_id, target_type FROM highlight_ignores "
            "WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def fetch_all_highlights(db: Any, guild_id: int) -> list[dict]:
        rows = await db.fetch(
            "SELECT user_id, keyword FROM highlights WHERE guild_id = $1",
            guild_id,
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
