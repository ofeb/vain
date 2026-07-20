from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild

from core.vain import Vain

logger = getLogger('vain.level.settings')


class Record(TypedDict, total=False):
    """DB row for `level_config`."""

    guild_id: int
    enabled: bool
    multiplier: int
    message: Any | None
    role_rewards: Any | None


class Settings:
    """Guild settings for `level_config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get('enabled'))

    @property
    def enabled(self) -> bool:
        return bool(self.record.get('enabled', True))

    @property
    def multiplier(self) -> int:
        return int(self.record.get('multiplier', 1) or 0)

    @property
    def message(self) -> Any | None:
        return self.record.get('message')

    @property
    def role_rewards(self) -> Any | None:
        return self.record.get('role_rewards')

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'enabled': True,
            'multiplier': 1,
            'message': None,
            'role_rewards': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM level_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'enabled': kwargs.get('enabled', self.enabled),
            'multiplier': kwargs.get('multiplier', self.multiplier),
            'message': kwargs.get('message', self.message),
            'role_rewards': kwargs.get('role_rewards', self.role_rewards),
        }
        query = """
        INSERT INTO level_config (guild_id, enabled, multiplier, message, role_rewards)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id) DO UPDATE SET
            enabled = EXCLUDED.enabled,
            multiplier = EXCLUDED.multiplier,
            message = EXCLUDED.message,
            role_rewards = EXCLUDED.role_rewards
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['enabled'],
            values['multiplier'],
            values['message'],
            values['role_rewards'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert level_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM level_config WHERE guild_id = $1",
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
