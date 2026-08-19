from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.giveaway.settings")


class Settings:
    """All `giveaways` rows for one guild (message_id, prize)."""

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
            "SELECT * FROM giveaways WHERE guild_id = $1",
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
        """Insert a row. Pass columns for `giveaways` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO giveaways (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add giveaways guild=%s fields=%s", self.guild.id, list(fields))
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
            "DELETE FROM giveaways WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM giveaways WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear giveaways guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self

    @staticmethod
    async def get_giveaway(db: Any, message_id: int) -> dict | None:
        row = await db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def update_max_level(db: Any, level: int, message_id: int) -> None:
        await db.execute(
            "UPDATE giveaways SET max_level = $1 WHERE message_id = $2",
            level,
            message_id,
        )

    @staticmethod
    async def update_prize(db: Any, prize: str, message_id: int) -> None:
        await db.execute(
            "UPDATE giveaways SET prize = $1 WHERE message_id = $2",
            prize,
            message_id,
        )

    @staticmethod
    async def update_expiration(db: Any, expiration: Any, message_id: int) -> None:
        await db.execute(
            "UPDATE giveaways SET expiration = $1 WHERE message_id = $2",
            expiration,
            message_id,
        )

    @staticmethod
    async def insert_giveaway(db: Any, payload: tuple, req_json: Any = None) -> None:
        import json as _json

        if req_json is not None:
            await db.execute(
                """
                INSERT INTO giveaways (
                    guild_id, channel_id, message_id, prize, expiration,
                    winner_count, hosts, entries, min_level, required_roles,
                    requirements, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11::jsonb, $12
                )
                ON CONFLICT (message_id) DO UPDATE SET
                    prize = EXCLUDED.prize,
                    expiration = EXCLUDED.expiration,
                    winner_count = EXCLUDED.winner_count,
                    hosts = EXCLUDED.hosts,
                    entries = EXCLUDED.entries,
                    min_level = EXCLUDED.min_level,
                    required_roles = EXCLUDED.required_roles,
                    requirements = EXCLUDED.requirements,
                    win_message_id = NULL
                """,
                *payload[:10],
                req_json,
                payload[10],
            )
        else:
            await db.execute(
                """
                INSERT INTO giveaways (
                    guild_id, channel_id, message_id, prize, expiration,
                    winner_count, hosts, entries, min_level, required_roles,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (message_id) DO UPDATE SET
                    prize = EXCLUDED.prize,
                    expiration = EXCLUDED.expiration,
                    winner_count = EXCLUDED.winner_count,
                    hosts = EXCLUDED.hosts,
                    entries = EXCLUDED.entries,
                    min_level = EXCLUDED.min_level,
                    required_roles = EXCLUDED.required_roles,
                    win_message_id = NULL
                """,
                *payload,
            )


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
