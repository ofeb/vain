from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.imgonly.settings")

CHANNELS_TABLE = "image_only"
MESSAGES_TABLE = "image_only_messages"


class Settings:
    """Gallery / image-only channel bindings for one guild."""

    def __init__(self, bot: Vain, guild: Guild, rows: list[dict[str, Any]] | None = None) -> None:
        self.bot = bot
        self.guild = guild
        self.rows = list(rows or [])

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @staticmethod
    async def ensure_schema(db) -> None:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHANNELS_TABLE} (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MESSAGES_TABLE} (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        await cls.ensure_schema(bot.db)
        rows = await bot.db.fetch(
            f"SELECT * FROM {CHANNELS_TABLE} WHERE guild_id = $1",
            guild.id,
        )
        return cls(bot, guild, [dict(r) for r in rows])

    async def reload(self) -> Settings:
        fresh = await Settings.fetch(self.bot, self.guild)
        self.rows = fresh.rows
        return self

    async def add(self, channel_id: int) -> None:
        await Settings.ensure_schema(self.bot.db)
        await self.bot.db.execute(
            f"""
            INSERT INTO {CHANNELS_TABLE} (guild_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id, channel_id) DO NOTHING
            """,
            self.guild.id,
            channel_id,
        )
        await self.reload()
        logger.debug("add image_only guild=%s channel=%s", self.guild.id, channel_id)

    async def remove(self, channel_id: int) -> None:
        await self.bot.db.execute(
            f"DELETE FROM {CHANNELS_TABLE} WHERE guild_id = $1 AND channel_id = $2",
            self.guild.id,
            channel_id,
        )
        await self.bot.db.execute(
            f"DELETE FROM {MESSAGES_TABLE} WHERE guild_id = $1 AND channel_id = $2",
            self.guild.id,
            channel_id,
        )
        await self.reload()
        logger.debug("remove image_only guild=%s channel=%s", self.guild.id, channel_id)

    async def channel_ids(self) -> list[int]:
        if not self.rows:
            await self.reload()
        return [int(r["channel_id"]) for r in self.rows]

    async def is_enabled(self, channel_id: int) -> bool:
        row = await self.bot.db.fetchval(
            f"SELECT 1 FROM {CHANNELS_TABLE} WHERE guild_id = $1 AND channel_id = $2",
            self.guild.id,
            channel_id,
        )
        return bool(row)

    async def get_message(self, channel_id: int) -> str | None:
        row = await self.bot.db.fetchrow(
            f"SELECT message FROM {MESSAGES_TABLE} WHERE guild_id = $1 AND channel_id = $2",
            self.guild.id,
            channel_id,
        )
        if not row:
            return None
        text = row["message"] if isinstance(row, dict) else getattr(row, "message", None)
        return str(text) if text else None

    async def set_message(self, channel_id: int, message: str) -> None:
        await Settings.ensure_schema(self.bot.db)
        await self.bot.db.execute(
            f"""
            INSERT INTO {MESSAGES_TABLE} (guild_id, channel_id, message)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, channel_id) DO UPDATE SET message = $3
            """,
            self.guild.id,
            channel_id,
            message,
        )
        logger.debug("set image_only message guild=%s channel=%s", self.guild.id, channel_id)
