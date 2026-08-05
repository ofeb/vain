from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.bump_reminder.settings')


class Record(TypedDict, total=False):
    """DB row for `bump_reminder`."""

    guild_id: int
    channel_id: Any | None
    role_id: Any | None
    message: Any | None
    enabled: bool


class Settings:
    """Guild settings for `bump_reminder`."""

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
    def channel_id(self) -> Any | None:
        return self.record.get('channel_id')

    @property
    def role_id(self) -> Any | None:
        return self.record.get('role_id')

    @property
    def message(self) -> Any | None:
        return self.record.get('message')

    @property
    def enabled(self) -> bool:
        return bool(self.record.get('enabled', True))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('channel_id')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def role(self) -> Role | None:
        rid = self.record.get('role_id')
        if not rid:
            return None
        return self.guild.get_role(int(rid))

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'channel_id': None,
            'role_id': None,
            'message': None,
            'enabled': True,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM bump_reminder WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM bump_reminder WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'channel_id': kwargs.get('channel_id', self.channel_id),
            'role_id': kwargs.get('role_id', self.role_id),
            'message': kwargs.get('message', self.message),
            'enabled': kwargs.get('enabled', self.enabled),
        }
        query = """
        INSERT INTO bump_reminder (guild_id, channel_id, role_id, message, enabled)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            role_id = EXCLUDED.role_id,
            message = EXCLUDED.message,
            enabled = EXCLUDED.enabled
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['channel_id'],
            values['role_id'],
            values['message'],
            values['enabled'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert bump_reminder guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM bump_reminder WHERE guild_id = $1",
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
