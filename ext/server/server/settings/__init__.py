from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.server.settings')


class Record(TypedDict, total=False):
    """DB row for `server_settings`."""

    guild_id: int
    jail_channel_id: Any | None
    jail_role_id: Any | None
    jail_message_channel_id: Any | None
    muted_role_id: Any | None
    imuted_role_id: Any | None
    rmuted_role_id: Any | None
    member_base_role_id: Any | None
    autonick: Any | None
    dj_role_id: Any | None
    premium_role_id: Any | None
    joinlog_channel_id: Any | None
    google_safety_level: bool
    disable_custom_fms: bool
    autoplay: Any | None
    jail_message: Any | None
    jail_remove_roles: bool
    antinuke_log_channel_id: Any | None
    antiraid_log_channel_id: Any | None


class Settings:
    """Guild settings for `server_settings`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('jail_role_id') is not None

    @property
    def jail_channel_id(self) -> Any | None:
        return self.record.get('jail_channel_id')

    @property
    def jail_role_id(self) -> Any | None:
        return self.record.get('jail_role_id')

    @property
    def jail_message_channel_id(self) -> Any | None:
        return self.record.get('jail_message_channel_id')

    @property
    def muted_role_id(self) -> Any | None:
        return self.record.get('muted_role_id')

    @property
    def imuted_role_id(self) -> Any | None:
        return self.record.get('imuted_role_id')

    @property
    def rmuted_role_id(self) -> Any | None:
        return self.record.get('rmuted_role_id')

    @property
    def member_base_role_id(self) -> Any | None:
        return self.record.get('member_base_role_id')

    @property
    def autonick(self) -> Any | None:
        return self.record.get('autonick')

    @property
    def dj_role_id(self) -> Any | None:
        return self.record.get('dj_role_id')

    @property
    def premium_role_id(self) -> Any | None:
        return self.record.get('premium_role_id')

    @property
    def joinlog_channel_id(self) -> Any | None:
        return self.record.get('joinlog_channel_id')

    @property
    def google_safety_level(self) -> bool:
        return bool(self.record.get('google_safety_level', False))

    @property
    def disable_custom_fms(self) -> bool:
        return bool(self.record.get('disable_custom_fms', False))

    @property
    def autoplay(self) -> Any | None:
        return self.record.get('autoplay')

    @property
    def jail_message(self) -> Any | None:
        return self.record.get('jail_message')

    @property
    def jail_remove_roles(self) -> bool:
        return bool(self.record.get('jail_remove_roles', True))

    @property
    def antinuke_log_channel_id(self) -> Any | None:
        return self.record.get('antinuke_log_channel_id')

    @property
    def antiraid_log_channel_id(self) -> Any | None:
        return self.record.get('antiraid_log_channel_id')

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('jail_channel_id')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def role(self) -> Role | None:
        rid = self.record.get('jail_role_id')
        if not rid:
            return None
        return self.guild.get_role(int(rid))

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'jail_channel_id': None,
            'jail_role_id': None,
            'jail_message_channel_id': None,
            'muted_role_id': None,
            'imuted_role_id': None,
            'rmuted_role_id': None,
            'member_base_role_id': None,
            'autonick': None,
            'dj_role_id': None,
            'premium_role_id': None,
            'joinlog_channel_id': None,
            'google_safety_level': False,
            'disable_custom_fms': False,
            'autoplay': None,
            'jail_message': None,
            'jail_remove_roles': True,
            'antinuke_log_channel_id': None,
            'antiraid_log_channel_id': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM server_settings WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM server_settings WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'jail_channel_id': kwargs.get('jail_channel_id', self.jail_channel_id),
            'jail_role_id': kwargs.get('jail_role_id', self.jail_role_id),
            'jail_message_channel_id': kwargs.get('jail_message_channel_id', self.jail_message_channel_id),
            'muted_role_id': kwargs.get('muted_role_id', self.muted_role_id),
            'imuted_role_id': kwargs.get('imuted_role_id', self.imuted_role_id),
            'rmuted_role_id': kwargs.get('rmuted_role_id', self.rmuted_role_id),
            'member_base_role_id': kwargs.get('member_base_role_id', self.member_base_role_id),
            'autonick': kwargs.get('autonick', self.autonick),
            'dj_role_id': kwargs.get('dj_role_id', self.dj_role_id),
            'premium_role_id': kwargs.get('premium_role_id', self.premium_role_id),
            'joinlog_channel_id': kwargs.get('joinlog_channel_id', self.joinlog_channel_id),
            'google_safety_level': kwargs.get('google_safety_level', self.google_safety_level),
            'disable_custom_fms': kwargs.get('disable_custom_fms', self.disable_custom_fms),
            'autoplay': kwargs.get('autoplay', self.autoplay),
            'jail_message': kwargs.get('jail_message', self.jail_message),
            'jail_remove_roles': kwargs.get('jail_remove_roles', self.jail_remove_roles),
            'antinuke_log_channel_id': kwargs.get('antinuke_log_channel_id', self.antinuke_log_channel_id),
            'antiraid_log_channel_id': kwargs.get('antiraid_log_channel_id', self.antiraid_log_channel_id),
        }
        query = """
        INSERT INTO server_settings (guild_id, jail_channel_id, jail_role_id, jail_message_channel_id, muted_role_id, imuted_role_id, rmuted_role_id, member_base_role_id, autonick, dj_role_id, premium_role_id, joinlog_channel_id, google_safety_level, disable_custom_fms, autoplay, jail_message, jail_remove_roles, antinuke_log_channel_id, antiraid_log_channel_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
        ON CONFLICT (guild_id) DO UPDATE SET
            jail_channel_id = EXCLUDED.jail_channel_id,
            jail_role_id = EXCLUDED.jail_role_id,
            jail_message_channel_id = EXCLUDED.jail_message_channel_id,
            muted_role_id = EXCLUDED.muted_role_id,
            imuted_role_id = EXCLUDED.imuted_role_id,
            rmuted_role_id = EXCLUDED.rmuted_role_id,
            member_base_role_id = EXCLUDED.member_base_role_id,
            autonick = EXCLUDED.autonick,
            dj_role_id = EXCLUDED.dj_role_id,
            premium_role_id = EXCLUDED.premium_role_id,
            joinlog_channel_id = EXCLUDED.joinlog_channel_id,
            google_safety_level = EXCLUDED.google_safety_level,
            disable_custom_fms = EXCLUDED.disable_custom_fms,
            autoplay = EXCLUDED.autoplay,
            jail_message = EXCLUDED.jail_message,
            jail_remove_roles = EXCLUDED.jail_remove_roles,
            antinuke_log_channel_id = EXCLUDED.antinuke_log_channel_id,
            antiraid_log_channel_id = EXCLUDED.antiraid_log_channel_id
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['jail_channel_id'],
            values['jail_role_id'],
            values['jail_message_channel_id'],
            values['muted_role_id'],
            values['imuted_role_id'],
            values['rmuted_role_id'],
            values['member_base_role_id'],
            values['autonick'],
            values['dj_role_id'],
            values['premium_role_id'],
            values['joinlog_channel_id'],
            values['google_safety_level'],
            values['disable_custom_fms'],
            values['autoplay'],
            values['jail_message'],
            values['jail_remove_roles'],
            values['antinuke_log_channel_id'],
            values['antiraid_log_channel_id'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert server_settings guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM server_settings WHERE guild_id = $1",
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
