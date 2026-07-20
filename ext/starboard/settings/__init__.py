from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.starboard.settings')


class Record(TypedDict, total=False):
    """DB row for `starboard`."""

    guild_id: int
    channel_id: Any | None
    emoji: str
    threshold: int
    lock: bool
    ignore_entries: Any | None
    attachments: bool
    ts: bool
    jump: bool
    self_star: bool
    color: Any | None


class Settings:
    """Guild settings for `starboard`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('channel_id') is not None

    @property
    def channel_id(self) -> Any | None:
        return self.record.get('channel_id')

    @property
    def emoji(self) -> str:
        return self.record.get('emoji', '⭐')

    @property
    def threshold(self) -> int:
        return int(self.record.get('threshold', 1) or 0)

    @property
    def lock(self) -> bool:
        return bool(self.record.get('lock', False))

    @property
    def ignore_entries(self) -> Any | None:
        return self.record.get('ignore_entries')

    @property
    def attachments(self) -> bool:
        return bool(self.record.get('attachments', False))

    @property
    def ts(self) -> bool:
        return bool(self.record.get('ts', False))

    @property
    def jump(self) -> bool:
        return bool(self.record.get('jump', False))

    @property
    def self_star(self) -> bool:
        return bool(self.record.get('self_star', True))

    @property
    def color(self) -> Any | None:
        return self.record.get('color')

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
            'channel_id': None,
            'emoji': '⭐',
            'threshold': 1,
            'lock': False,
            'ignore_entries': None,
            'attachments': False,
            'ts': False,
            'jump': False,
            'self_star': True,
            'color': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM starboard WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM starboard WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'channel_id': kwargs.get('channel_id', self.channel_id),
            'emoji': kwargs.get('emoji', self.emoji),
            'threshold': kwargs.get('threshold', self.threshold),
            'lock': kwargs.get('lock', self.lock),
            'ignore_entries': kwargs.get('ignore_entries', self.ignore_entries),
            'attachments': kwargs.get('attachments', self.attachments),
            'ts': kwargs.get('ts', self.ts),
            'jump': kwargs.get('jump', self.jump),
            'self_star': kwargs.get('self_star', self.self_star),
            'color': kwargs.get('color', self.color),
        }
        query = """
        INSERT INTO starboard (guild_id, channel_id, emoji, threshold, lock, ignore_entries, attachments, ts, jump, self_star, color)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            emoji = EXCLUDED.emoji,
            threshold = EXCLUDED.threshold,
            lock = EXCLUDED.lock,
            ignore_entries = EXCLUDED.ignore_entries,
            attachments = EXCLUDED.attachments,
            ts = EXCLUDED.ts,
            jump = EXCLUDED.jump,
            self_star = EXCLUDED.self_star,
            color = EXCLUDED.color
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['channel_id'],
            values['emoji'],
            values['threshold'],
            values['lock'],
            values['ignore_entries'],
            values['attachments'],
            values['ts'],
            values['jump'],
            values['self_star'],
            values['color'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert starboard guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM starboard WHERE guild_id = $1",
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
