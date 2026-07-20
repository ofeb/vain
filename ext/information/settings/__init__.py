from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.information.settings')


class Record(TypedDict, total=False):
    """DB row for `information_config`."""

    guild_id: int
    info_channel: Any | None
    join_info_enabled: bool
    leave_info_enabled: bool
    edit_info_enabled: bool
    delete_info_enabled: bool


class Settings:
    """Guild settings for `information_config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('info_channel') is not None

    @property
    def info_channel(self) -> Any | None:
        return self.record.get('info_channel')

    @property
    def join_info_enabled(self) -> bool:
        return bool(self.record.get('join_info_enabled', False))

    @property
    def leave_info_enabled(self) -> bool:
        return bool(self.record.get('leave_info_enabled', False))

    @property
    def edit_info_enabled(self) -> bool:
        return bool(self.record.get('edit_info_enabled', False))

    @property
    def delete_info_enabled(self) -> bool:
        return bool(self.record.get('delete_info_enabled', False))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('info_channel')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'info_channel': None,
            'join_info_enabled': False,
            'leave_info_enabled': False,
            'edit_info_enabled': False,
            'delete_info_enabled': False,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM information_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM information_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'info_channel': kwargs.get('info_channel', self.info_channel),
            'join_info_enabled': kwargs.get('join_info_enabled', self.join_info_enabled),
            'leave_info_enabled': kwargs.get('leave_info_enabled', self.leave_info_enabled),
            'edit_info_enabled': kwargs.get('edit_info_enabled', self.edit_info_enabled),
            'delete_info_enabled': kwargs.get('delete_info_enabled', self.delete_info_enabled),
        }
        query = """
        INSERT INTO information_config (guild_id, info_channel, join_info_enabled, leave_info_enabled, edit_info_enabled, delete_info_enabled)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (guild_id) DO UPDATE SET
            info_channel = EXCLUDED.info_channel,
            join_info_enabled = EXCLUDED.join_info_enabled,
            leave_info_enabled = EXCLUDED.leave_info_enabled,
            edit_info_enabled = EXCLUDED.edit_info_enabled,
            delete_info_enabled = EXCLUDED.delete_info_enabled
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['info_channel'],
            values['join_info_enabled'],
            values['leave_info_enabled'],
            values['edit_info_enabled'],
            values['delete_info_enabled'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert information_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM information_config WHERE guild_id = $1",
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
