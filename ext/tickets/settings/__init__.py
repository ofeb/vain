from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild

from core.vain import Vain

logger = getLogger('vain.tickets.settings')


class Record(TypedDict, total=False):
    """DB row for `ticket_settings`."""

    guild_id: int
    log_channel_id: Any | None
    transcript_channel_id: Any | None
    category_id: Any | None
    support_role_ids: list[Any]
    greeting_message: Any | None
    close_message: Any | None
    creator_can_close: bool
    claim_enabled: bool
    max_open_per_user: int
    channel_name_format: str
    blacklist_user_ids: list[Any]
    transcript_admin_ids: list[Any]
    ticket_counter: int
    counter_enabled: bool
    config: dict[str, Any]


class Settings:
    """Guild settings for `ticket_settings`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('category_id') is not None

    @property
    def log_channel_id(self) -> Any | None:
        return self.record.get('log_channel_id')

    @property
    def transcript_channel_id(self) -> Any | None:
        return self.record.get('transcript_channel_id')

    @property
    def category_id(self) -> Any | None:
        return self.record.get('category_id')

    @property
    def support_role_ids(self) -> list[Any]:
        return list(self.record.get('support_role_ids') or [])

    @property
    def greeting_message(self) -> Any | None:
        return self.record.get('greeting_message')

    @property
    def close_message(self) -> Any | None:
        return self.record.get('close_message')

    @property
    def creator_can_close(self) -> bool:
        return bool(self.record.get('creator_can_close', True))

    @property
    def claim_enabled(self) -> bool:
        return bool(self.record.get('claim_enabled', True))

    @property
    def max_open_per_user(self) -> int:
        return int(self.record.get('max_open_per_user', 1) or 0)

    @property
    def channel_name_format(self) -> str:
        return self.record.get('channel_name_format', 'ticket-{user}')

    @property
    def blacklist_user_ids(self) -> list[Any]:
        return list(self.record.get('blacklist_user_ids') or [])

    @property
    def transcript_admin_ids(self) -> list[Any]:
        return list(self.record.get('transcript_admin_ids') or [])

    @property
    def ticket_counter(self) -> int:
        return int(self.record.get('ticket_counter', 0) or 0)

    @property
    def counter_enabled(self) -> bool:
        return bool(self.record.get('counter_enabled', False))

    @property
    def config(self) -> dict[str, Any]:
        return dict(self.record.get('config') or {})

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'log_channel_id': None,
            'transcript_channel_id': None,
            'category_id': None,
            'support_role_ids': [],
            'greeting_message': None,
            'close_message': None,
            'creator_can_close': True,
            'claim_enabled': True,
            'max_open_per_user': 1,
            'channel_name_format': 'ticket-{user}',
            'blacklist_user_ids': [],
            'transcript_admin_ids': [],
            'ticket_counter': 0,
            'counter_enabled': False,
            'config': {},
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM ticket_settings WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM ticket_settings WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'log_channel_id': kwargs.get('log_channel_id', self.log_channel_id),
            'transcript_channel_id': kwargs.get('transcript_channel_id', self.transcript_channel_id),
            'category_id': kwargs.get('category_id', self.category_id),
            'support_role_ids': kwargs.get('support_role_ids', self.support_role_ids),
            'greeting_message': kwargs.get('greeting_message', self.greeting_message),
            'close_message': kwargs.get('close_message', self.close_message),
            'creator_can_close': kwargs.get('creator_can_close', self.creator_can_close),
            'claim_enabled': kwargs.get('claim_enabled', self.claim_enabled),
            'max_open_per_user': kwargs.get('max_open_per_user', self.max_open_per_user),
            'channel_name_format': kwargs.get('channel_name_format', self.channel_name_format),
            'blacklist_user_ids': kwargs.get('blacklist_user_ids', self.blacklist_user_ids),
            'transcript_admin_ids': kwargs.get('transcript_admin_ids', self.transcript_admin_ids),
            'ticket_counter': kwargs.get('ticket_counter', self.ticket_counter),
            'counter_enabled': kwargs.get('counter_enabled', self.counter_enabled),
            'config': kwargs.get('config', self.config),
        }
        query = """
        INSERT INTO ticket_settings (guild_id, log_channel_id, transcript_channel_id, category_id, support_role_ids, greeting_message, close_message, creator_can_close, claim_enabled, max_open_per_user, channel_name_format, blacklist_user_ids, transcript_admin_ids, ticket_counter, counter_enabled, config)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        ON CONFLICT (guild_id) DO UPDATE SET
            log_channel_id = EXCLUDED.log_channel_id,
            transcript_channel_id = EXCLUDED.transcript_channel_id,
            category_id = EXCLUDED.category_id,
            support_role_ids = EXCLUDED.support_role_ids,
            greeting_message = EXCLUDED.greeting_message,
            close_message = EXCLUDED.close_message,
            creator_can_close = EXCLUDED.creator_can_close,
            claim_enabled = EXCLUDED.claim_enabled,
            max_open_per_user = EXCLUDED.max_open_per_user,
            channel_name_format = EXCLUDED.channel_name_format,
            blacklist_user_ids = EXCLUDED.blacklist_user_ids,
            transcript_admin_ids = EXCLUDED.transcript_admin_ids,
            ticket_counter = EXCLUDED.ticket_counter,
            counter_enabled = EXCLUDED.counter_enabled,
            config = EXCLUDED.config
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['log_channel_id'],
            values['transcript_channel_id'],
            values['category_id'],
            values['support_role_ids'],
            values['greeting_message'],
            values['close_message'],
            values['creator_can_close'],
            values['claim_enabled'],
            values['max_open_per_user'],
            values['channel_name_format'],
            values['blacklist_user_ids'],
            values['transcript_admin_ids'],
            values['ticket_counter'],
            values['counter_enabled'],
            values['config'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert ticket_settings guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM ticket_settings WHERE guild_id = $1",
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
