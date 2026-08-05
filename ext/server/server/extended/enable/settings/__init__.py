from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.server.extended.enable.settings")

TABLES = ("disabled_commands", "disabled_events", "disabled_modules")


class Settings:
    """All disable/enable restriction rows for a guild."""

    bot: Vain
    guild: Guild
    data: dict[str, list[dict[str, Any]]]

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        data: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.data = dict(data or {t: [] for t in TABLES})

    def __bool__(self) -> bool:
        return any(self.data.values())

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        data: dict[str, list[dict[str, Any]]] = {}
        for table in TABLES:
            rows = await bot.db.fetch(
                f"SELECT * FROM {table} WHERE guild_id = $1",
                guild.id,
            )
            data[table] = [dict(r) for r in rows]
        return cls(bot, guild, data)

    async def upsert(self, **kwargs: Any) -> Settings:
        return await Settings.fetch(self.bot, self.guild)

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await Settings.fetch(bot, guild)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await Settings.fetch(bot, guild)


__all__ = ["Settings", "TABLES", "fetch", "upsert", "insert"]
