from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.fun.settings')


class Record(TypedDict, total=False):
    """DB row for `fun_config`."""

    guild_id: int
    reaction_rewards: bool
    welcome_enabled: bool
    welcome_channel: Any | None


class Settings:
    """Guild settings for `fun_config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('welcome_enabled') is not None

    @property
    def reaction_rewards(self) -> bool:
        return bool(self.record.get('reaction_rewards', False))

    @property
    def welcome_enabled(self) -> bool:
        return bool(self.record.get('welcome_enabled', False))

    @property
    def welcome_channel(self) -> Any | None:
        return self.record.get('welcome_channel')

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('welcome_channel')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'reaction_rewards': False,
            'welcome_enabled': False,
            'welcome_channel': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM fun_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM fun_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'reaction_rewards': kwargs.get('reaction_rewards', self.reaction_rewards),
            'welcome_enabled': kwargs.get('welcome_enabled', self.welcome_enabled),
            'welcome_channel': kwargs.get('welcome_channel', self.welcome_channel),
        }
        query = """
        INSERT INTO fun_config (guild_id, reaction_rewards, welcome_enabled, welcome_channel)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id) DO UPDATE SET
            reaction_rewards = EXCLUDED.reaction_rewards,
            welcome_enabled = EXCLUDED.welcome_enabled,
            welcome_channel = EXCLUDED.welcome_channel
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['reaction_rewards'],
            values['welcome_enabled'],
            values['welcome_channel'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert fun_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM fun_config WHERE guild_id = $1",
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
