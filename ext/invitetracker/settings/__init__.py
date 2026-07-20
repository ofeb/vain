from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.invitetracker.settings')


class Record(TypedDict, total=False):
    """DB row for `invite_config`."""

    guild_id: int
    enabled: bool
    channel_id: Any | None
    message: str
    leave_message: str
    fake_remove: bool


class Settings:
    """Guild settings for `invite_config`."""

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
        return bool(self.record.get('enabled', False))

    @property
    def channel_id(self) -> Any | None:
        return self.record.get('channel_id')

    @property
    def message(self) -> str:
        return self.record.get('message', '{inviter.mention} invited {invitee.mention}. They have **{invites}** {invite_word}.')

    @property
    def leave_message(self) -> str:
        return self.record.get('leave_message', '{invitee.mention} left. {inviter.mention} now has **{invites}** {invite_word}.')

    @property
    def fake_remove(self) -> bool:
        return bool(self.record.get('fake_remove', True))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('channel_id')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'enabled': False,
            'channel_id': None,
            'message': '{inviter.mention} invited {invitee.mention}. They have **{invites}** {invite_word}.',
            'leave_message': '{invitee.mention} left. {inviter.mention} now has **{invites}** {invite_word}.',
            'fake_remove': True,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM invite_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM invite_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'enabled': kwargs.get('enabled', self.enabled),
            'channel_id': kwargs.get('channel_id', self.channel_id),
            'message': kwargs.get('message', self.message),
            'leave_message': kwargs.get('leave_message', self.leave_message),
            'fake_remove': kwargs.get('fake_remove', self.fake_remove),
        }
        query = """
        INSERT INTO invite_config (guild_id, enabled, channel_id, message, leave_message, fake_remove)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (guild_id) DO UPDATE SET
            enabled = EXCLUDED.enabled,
            channel_id = EXCLUDED.channel_id,
            message = EXCLUDED.message,
            leave_message = EXCLUDED.leave_message,
            fake_remove = EXCLUDED.fake_remove
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['enabled'],
            values['channel_id'],
            values['message'],
            values['leave_message'],
            values['fake_remove'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert invite_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM invite_config WHERE guild_id = $1",
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
