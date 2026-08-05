from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.moderation.settings')


class Record(TypedDict, total=False):
    """DB row for `moderation_config`."""

    guild_id: int
    log_channel: Any | None
    role_change_logging: bool
    ban_logging: bool


class Settings:
    """Guild settings for `moderation_config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('log_channel') is not None

    @property
    def log_channel(self) -> Any | None:
        return self.record.get('log_channel')

    @property
    def role_change_logging(self) -> bool:
        return bool(self.record.get('role_change_logging', False))

    @property
    def ban_logging(self) -> bool:
        return bool(self.record.get('ban_logging', False))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('log_channel')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'log_channel': None,
            'role_change_logging': False,
            'ban_logging': False,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM moderation_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM moderation_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'log_channel': kwargs.get('log_channel', self.log_channel),
            'role_change_logging': kwargs.get('role_change_logging', self.role_change_logging),
            'ban_logging': kwargs.get('ban_logging', self.ban_logging),
        }
        query = """
        INSERT INTO moderation_config (guild_id, log_channel, role_change_logging, ban_logging)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id) DO UPDATE SET
            log_channel = EXCLUDED.log_channel,
            role_change_logging = EXCLUDED.role_change_logging,
            ban_logging = EXCLUDED.ban_logging
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['log_channel'],
            values['role_change_logging'],
            values['ban_logging'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert moderation_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM moderation_config WHERE guild_id = $1",
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
