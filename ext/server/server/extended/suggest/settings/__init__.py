from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.server.extended.suggest.settings')


class Record(TypedDict, total=False):
    """DB row for `suggest_settings`."""

    guild_id: int
    enabled: bool
    channel_id: Any | None
    review_enabled: bool
    review_channel_id: Any | None
    threads_enabled: bool
    upvote_emoji: str
    downvote_emoji: str


class Settings:
    """Guild settings for `suggest_settings`."""

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
    def review_enabled(self) -> bool:
        return bool(self.record.get('review_enabled', False))

    @property
    def review_channel_id(self) -> Any | None:
        return self.record.get('review_channel_id')

    @property
    def threads_enabled(self) -> bool:
        return bool(self.record.get('threads_enabled', False))

    @property
    def upvote_emoji(self) -> str:
        return self.record.get('upvote_emoji', '✅')

    @property
    def downvote_emoji(self) -> str:
        return self.record.get('downvote_emoji', '❌')

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
            'review_enabled': False,
            'review_channel_id': None,
            'threads_enabled': False,
            'upvote_emoji': '✅',
            'downvote_emoji': '❌',
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM suggest_settings WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM suggest_settings WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'enabled': kwargs.get('enabled', self.enabled),
            'channel_id': kwargs.get('channel_id', self.channel_id),
            'review_enabled': kwargs.get('review_enabled', self.review_enabled),
            'review_channel_id': kwargs.get('review_channel_id', self.review_channel_id),
            'threads_enabled': kwargs.get('threads_enabled', self.threads_enabled),
            'upvote_emoji': kwargs.get('upvote_emoji', self.upvote_emoji),
            'downvote_emoji': kwargs.get('downvote_emoji', self.downvote_emoji),
        }
        query = """
        INSERT INTO suggest_settings (guild_id, enabled, channel_id, review_enabled, review_channel_id, threads_enabled, upvote_emoji, downvote_emoji)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (guild_id) DO UPDATE SET
            enabled = EXCLUDED.enabled,
            channel_id = EXCLUDED.channel_id,
            review_enabled = EXCLUDED.review_enabled,
            review_channel_id = EXCLUDED.review_channel_id,
            threads_enabled = EXCLUDED.threads_enabled,
            upvote_emoji = EXCLUDED.upvote_emoji,
            downvote_emoji = EXCLUDED.downvote_emoji
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['enabled'],
            values['channel_id'],
            values['review_enabled'],
            values['review_channel_id'],
            values['threads_enabled'],
            values['upvote_emoji'],
            values['downvote_emoji'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert suggest_settings guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM suggest_settings WHERE guild_id = $1",
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
