from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.manipulation.settings')


class Record(TypedDict, total=False):
    """DB row for `manipulation_config`."""

    guild_id: int
    auto_delete: bool
    delete_patterns: list[Any]
    auto_reply: bool
    auto_replies: dict[str, Any]
    auto_role_on_join: bool
    join_role_id: Any | None


class Settings:
    """Guild settings for `manipulation_config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('auto_delete') is not None

    @property
    def auto_delete(self) -> bool:
        return bool(self.record.get('auto_delete', False))

    @property
    def delete_patterns(self) -> list[Any]:
        return list(self.record.get('delete_patterns') or [])

    @property
    def auto_reply(self) -> bool:
        return bool(self.record.get('auto_reply', False))

    @property
    def auto_replies(self) -> dict[str, Any]:
        return dict(self.record.get('auto_replies') or {})

    @property
    def auto_role_on_join(self) -> bool:
        return bool(self.record.get('auto_role_on_join', False))

    @property
    def join_role_id(self) -> Any | None:
        return self.record.get('join_role_id')

    @property
    def role(self) -> Role | None:
        rid = self.record.get('join_role_id')
        if not rid:
            return None
        return self.guild.get_role(int(rid))

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'auto_delete': False,
            'delete_patterns': [],
            'auto_reply': False,
            'auto_replies': {},
            'auto_role_on_join': False,
            'join_role_id': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM manipulation_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM manipulation_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'auto_delete': kwargs.get('auto_delete', self.auto_delete),
            'delete_patterns': kwargs.get('delete_patterns', self.delete_patterns),
            'auto_reply': kwargs.get('auto_reply', self.auto_reply),
            'auto_replies': kwargs.get('auto_replies', self.auto_replies),
            'auto_role_on_join': kwargs.get('auto_role_on_join', self.auto_role_on_join),
            'join_role_id': kwargs.get('join_role_id', self.join_role_id),
        }
        query = """
        INSERT INTO manipulation_config (guild_id, auto_delete, delete_patterns, auto_reply, auto_replies, auto_role_on_join, join_role_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (guild_id) DO UPDATE SET
            auto_delete = EXCLUDED.auto_delete,
            delete_patterns = EXCLUDED.delete_patterns,
            auto_reply = EXCLUDED.auto_reply,
            auto_replies = EXCLUDED.auto_replies,
            auto_role_on_join = EXCLUDED.auto_role_on_join,
            join_role_id = EXCLUDED.join_role_id
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['auto_delete'],
            values['delete_patterns'],
            values['auto_reply'],
            values['auto_replies'],
            values['auto_role_on_join'],
            values['join_role_id'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert manipulation_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM manipulation_config WHERE guild_id = $1",
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
