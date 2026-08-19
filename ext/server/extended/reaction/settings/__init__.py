from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.reaction.settings")


class Settings:
    """All `auto_reactions` rows for one guild (channel_id, emoji, response)."""

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
            "SELECT * FROM auto_reactions WHERE guild_id = $1",
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
        """Insert a row. Pass columns for `auto_reactions` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO auto_reactions (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add auto_reactions guild=%s fields=%s", self.guild.id, list(fields))
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
            "DELETE FROM auto_reactions WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear auto_reactions guild=%s", self.guild.id)

    async def upsert_reaction(
        self,
        guild_id: int,
        trigger: str,
        response: list,
        owner_id: int,
        strict: bool,
        reply: bool,
    ) -> None:
        await self.bot.db.execute(
            """
            INSERT INTO auto_reactions (guild_id, trigger, response, owner_id, strict, reply)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, trigger, response)
            DO UPDATE SET
                response = EXCLUDED.response,
                owner_id = EXCLUDED.owner_id,
                strict = EXCLUDED.strict,
                reply = EXCLUDED.reply
            """,
            guild_id,
            trigger,
            response,
            owner_id,
            strict,
            reply,
        )

    async def delete_by_trigger(self, guild_id: int, trigger: str) -> str:
        return await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1 AND LOWER(trigger) = LOWER($2)",
            guild_id,
            trigger,
        )

    async def delete_by_trigger_and_key(
        self, guild_id: int, trigger: str, key: str
    ) -> str:
        return await self.bot.db.execute(
            """
            DELETE FROM auto_reactions
            WHERE guild_id = $1 AND (
                LOWER(trigger) = LOWER($2) OR trigger = $3
            )
            """,
            guild_id,
            trigger,
            key,
        )

    async def delete_by_channel(self, guild_id: int, channel_id: str) -> None:
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1 AND trigger = $2",
            guild_id,
            channel_id,
        )

    async def delete_by_word(self, guild_id: int, trigger_word: str) -> None:
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE LOWER(trigger) = LOWER($1) AND guild_id = $2",
            trigger_word,
            guild_id,
        )

    async def update_strict_all(self, guild_id: int, strict: bool) -> None:
        await self.bot.db.execute(
            "UPDATE auto_reactions SET strict = $2 WHERE guild_id = $1",
            guild_id,
            strict,
        )

    async def update_strict(
        self, guild_id: int, trigger: str, strict: bool
    ) -> None:
        await self.bot.db.execute(
            """
            UPDATE auto_reactions SET strict = $3
            WHERE guild_id = $1 AND LOWER(trigger) = LOWER($2)
            """,
            guild_id,
            trigger,
            strict,
        )

    async def fetch_all_reactions(
        self, guild_id: int
    ) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetch(
            "SELECT trigger, response FROM auto_reactions WHERE guild_id = $1",
            guild_id,
        )
        return [dict(r) for r in rows]

    async def fetch_all_with_strict(
        self, guild_id: int
    ) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetch(
            """
            SELECT trigger, response, strict FROM auto_reactions
            WHERE guild_id = $1
            ORDER BY trigger
            """,
            guild_id,
        )
        return [dict(r) for r in rows]

    async def fetch_owner_id(
        self, guild_id: int, trigger: str
    ) -> int | None:
        return await self.bot.db.fetchval(
            """
            SELECT owner_id FROM auto_reactions
            WHERE LOWER(trigger) = LOWER($1) AND guild_id = $2
            LIMIT 1
            """,
            trigger,
            guild_id,
        )

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

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
