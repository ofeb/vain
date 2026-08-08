from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.fun.extended.uwulock.settings")


class Settings:
    """All `uwulocks` rows for one guild (guild_id, user_id)."""

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
    async def ensure_table(cls, bot: Vain) -> None:
        if getattr(bot.db, "pool", None) is None:
            return
        with contextlib.suppress(Exception):
            await bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS uwulocks (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        await cls.ensure_table(bot)
        if getattr(bot.db, "pool", None) is None:
            return cls(bot, guild, [])
        rows = await bot.db.fetch(
            "SELECT * FROM uwulocks WHERE guild_id = $1",
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

    def is_locked(self, user_id: int) -> bool:
        return any(int(r.get("user_id")) == int(user_id) for r in self.rows)

    async def add(self, user_id: int) -> None:
        await self.bot.db.execute(
            """
            INSERT INTO uwulocks (guild_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            self.guild.id,
            user_id,
        )
        if not self.is_locked(user_id):
            self.rows.append({"guild_id": self.guild.id, "user_id": user_id})
        logger.debug("add uwulock guild=%s user=%s", self.guild.id, user_id)

    async def remove(self, user_id: int) -> bool:
        result = await self.bot.db.execute(
            "DELETE FROM uwulocks WHERE guild_id = $1 AND user_id = $2",
            self.guild.id,
            user_id,
        )
        self.rows = [r for r in self.rows if int(r.get("user_id")) != int(user_id)]
        try:
            return int(str(result).split()[-1]) > 0
        except Exception:
            return False

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM uwulocks WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear uwulocks guild=%s", self.guild.id)


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def fetch_all(bot: Vain, guild: Guild) -> list[dict[str, Any]]:
    return await Settings.fetch_all(bot, guild)


__all__ = ["Settings", "fetch", "fetch_all"]
