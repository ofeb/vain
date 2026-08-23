from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.server.extended.alias.settings")


class Settings:
    """All `aliases` rows for one guild (alias, command_name)."""

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
            "SELECT * FROM aliases WHERE guild_id = $1",
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
        """Insert a row. Pass columns for `aliases` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO aliases (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add aliases guild=%s fields=%s", self.guild.id, list(fields))
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
            "DELETE FROM aliases WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM aliases WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear aliases guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    

    @staticmethod
    async def ensure_schema(db: Any) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS selfaliases (
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                invoke TEXT NOT NULL,
                command TEXT NOT NULL,
                with_parameters BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, name)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS aliases (
                guild_id BIGINT NOT NULL,
                command_name TEXT NOT NULL,
                alias TEXT NOT NULL,
                with_parameters BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, alias)
            )
            """
        )
        await db.execute(
            "ALTER TABLE aliases ADD COLUMN IF NOT EXISTS with_parameters BOOLEAN DEFAULT FALSE"
        )
        await db.execute(
            "ALTER TABLE selfaliases ADD COLUMN IF NOT EXISTS with_parameters BOOLEAN DEFAULT FALSE"
        )

    

    @staticmethod
    async def add_selfalias(
        db: Any, user_id: int, name: str, invoke: str, command: str, with_parameters: bool = False
    ) -> None:
        await db.execute(
            """
            INSERT INTO selfaliases (user_id, name, invoke, command, with_parameters)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, name) DO UPDATE
            SET invoke = EXCLUDED.invoke, command = EXCLUDED.command, with_parameters = EXCLUDED.with_parameters
            """,
            user_id,
            name,
            invoke,
            command,
            with_parameters,
        )

    @staticmethod
    async def remove_selfalias(db: Any, user_id: int, name: str) -> int:
        result = await db.execute(
            "DELETE FROM selfaliases WHERE user_id = $1 AND name = $2",
            user_id,
            name,
        )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    @staticmethod
    async def get_selfalias(db: Any, user_id: int, name: str) -> str | None:
        row = await db.fetchrow(
            "SELECT invoke FROM selfaliases WHERE user_id = $1 AND name = $2",
            user_id,
            name,
        )
        if not row:
            return None
        return row["invoke"] if hasattr(row, "keys") else row[0]

    @staticmethod
    async def clear_selfaliases(db: Any, user_id: int) -> int:
        result = await db.execute(
            "DELETE FROM selfaliases WHERE user_id = $1",
            user_id,
        )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    @staticmethod
    async def fetch_selfaliases(db: Any, user_id: int) -> list[dict[str, Any]]:
        rows = await db.fetch(
            """
            SELECT name, invoke FROM selfaliases
            WHERE user_id = $1
            ORDER BY name ASC
            """,
            user_id,
        )
        return [dict(r) for r in rows]

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self


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
