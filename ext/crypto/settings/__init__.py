from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.crypto.settings")


class Settings:
    """All `crypto_alerts` rows for one guild (user_id, coin, threshold)."""

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
            "SELECT * FROM crypto_alerts WHERE guild_id = $1",
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
        """Insert a row. Pass columns for `crypto_alerts` except guild_id."""
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO crypto_alerts (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        logger.debug("add crypto_alerts guild=%s fields=%s", self.guild.id, list(fields))
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
            "DELETE FROM crypto_alerts WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM crypto_alerts WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear crypto_alerts guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self

    @staticmethod
    async def ensure_schema(db: Any) -> None:
        with contextlib.suppress(Exception):
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS crypto_feeds (
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    coin_id TEXT NOT NULL,
                    coin_label TEXT NOT NULL,
                    last_price DOUBLE PRECISION,
                    last_change DOUBLE PRECISION,
                    last_market_cap DOUBLE PRECISION,
                    last_posted TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, channel_id, coin_id)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_crypto_feeds_coin ON crypto_feeds(coin_id)"
            )

    @staticmethod
    async def upsert_feed(
        db: Any,
        guild_id: int,
        channel_id: int,
        coin_id: str,
        coin_label: str,
    ) -> None:
        await db.execute(
            """
            INSERT INTO crypto_feeds (guild_id, channel_id, coin_id, coin_label)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, channel_id, coin_id) DO UPDATE
                SET coin_label = excluded.coin_label
            """,
            guild_id,
            channel_id,
            coin_id,
            coin_label,
        )

    @staticmethod
    async def update_feed_price(
        db: Any,
        guild_id: int,
        channel_id: int,
        coin_id: str,
        last_price: float,
        last_change: float,
        last_market_cap: float,
    ) -> None:
        await db.execute(
            """
            UPDATE crypto_feeds
               SET last_price = $1, last_change = $2, last_market_cap = $3
             WHERE guild_id = $4 AND channel_id = $5 AND coin_id = $6
            """,
            last_price,
            last_change,
            last_market_cap,
            guild_id,
            channel_id,
            coin_id,
        )

    @staticmethod
    async def update_feed_price_with_posted(
        db: Any,
        guild_id: int,
        channel_id: int,
        coin_id: str,
        last_price: float,
        last_change: float,
        last_market_cap: float,
        last_posted: Any,
    ) -> None:
        await db.execute(
            """
            UPDATE crypto_feeds
               SET last_price = $1,
                   last_change = $2,
                   last_market_cap = $3,
                   last_posted = $4
             WHERE guild_id = $5 AND channel_id = $6 AND coin_id = $7
            """,
            last_price,
            last_change,
            last_market_cap,
            last_posted,
            guild_id,
            channel_id,
            coin_id,
        )

    @staticmethod
    async def remove_feed(db: Any, guild_id: int, channel_id: int) -> None:
        await db.execute(
            "DELETE FROM crypto_feeds WHERE guild_id = $1 AND channel_id = $2",
            guild_id,
            channel_id,
        )

    @staticmethod
    async def remove_feed_coin(db: Any, guild_id: int, channel_id: int, coin_id: str) -> dict | None:
        row = await db.fetchrow(
            """
            DELETE FROM crypto_feeds
             WHERE guild_id = $1 AND channel_id = $2 AND coin_id = $3
         RETURNING coin_label
            """,
            guild_id,
            channel_id,
            coin_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def fetch_feeds(db: Any, guild_id: int) -> list[dict]:
        rows = await db.fetch(
            """
            SELECT channel_id, coin_id, coin_label, last_price, last_change
              FROM crypto_feeds
             WHERE guild_id = $1
             ORDER BY coin_label, channel_id
            """,
            guild_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def fetch_all_feeds(db: Any) -> list[dict]:
        rows = await db.fetch("SELECT * FROM crypto_feeds")
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
