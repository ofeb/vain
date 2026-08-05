from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild

from core.vain import Vain

logger = getLogger('vain.lastfm.settings')


class Record(TypedDict, total=False):
    """DB row for `lastfm_guild_settings`."""

    guild_id: int
    upvote: Any | None
    downvote: Any | None


class Settings:
    """Guild settings for `lastfm_guild_settings`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('upvote') is not None

    @property
    def upvote(self) -> Any | None:
        return self.record.get('upvote')

    @property
    def downvote(self) -> Any | None:
        return self.record.get('downvote')

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'upvote': None,
            'downvote': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM lastfm_guild_settings WHERE guild_id = $1",
            guild.id,
        )
        if row is None:
            data = cls._default_config()
            data["guild_id"] = guild.id
            return cls(bot, guild, data)
        return cls(bot, guild, dict(row))

    @classmethod
    async def exists(cls, bot: Vain, guild: Guild) -> bool:
        return bool(
            await bot.db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM lastfm_guild_settings WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'upvote': kwargs.get('upvote', self.upvote),
            'downvote': kwargs.get('downvote', self.downvote),
        }
        query = """
        INSERT INTO lastfm_guild_settings (guild_id, upvote, downvote)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id) DO UPDATE SET
            upvote = EXCLUDED.upvote,
            downvote = EXCLUDED.downvote
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['upvote'],
            values['downvote'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert lastfm_guild_settings guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM lastfm_guild_settings WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
