from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild

from core.vain import Vain

logger = getLogger('vain.lastfm.settings')


class Record(TypedDict, total=False):
    """DB row for `lastfm_guild_settings`."""

    guild_id: int
    upvote: Any | None
    downvote: Any | None


class Settings:
    """Facade for all Last.fm database operations."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('upvote') is not None

    @property
    def upvote(self) -> Any | None:
        return self.record.get('upvote')

    @property
    def downvote(self) -> Any | None:
        return self.record.get('downvote')

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'upvote': None,
            'downvote': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM lastfm_guild_settings WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM lastfm_guild_settings WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'upvote': kwargs.get('upvote', self.upvote),
            'downvote': kwargs.get('downvote', self.downvote),
        }
        query = """
        INSERT INTO lastfm_guild_settings (guild_id, upvote, downvote)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id) DO UPDATE SET
            upvote = EXCLUDED.upvote,
            downvote = EXCLUDED.downvote
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['upvote'],
            values['downvote'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert lastfm_guild_settings guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM lastfm_guild_settings WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    
    
    

    @staticmethod
    async def get_user(bot: Vain, user_id: int) -> dict | None:
        return await bot.db.get_lastfm_user(user_id)

    @staticmethod
    async def set_user(bot: Vain, user_id: int, username: str, session_key: str | None) -> None:
        await bot.db.set_lastfm_user(user_id, username, session_key)

    @staticmethod
    async def remove_user(bot: Vain, user_id: int) -> None:
        await bot.db.remove_lastfm_user(user_id)

    @staticmethod
    async def get_users(bot: Vain) -> list[dict]:
        return await bot.db.get_lastfm_users()

    @staticmethod
    async def get_color(bot: Vain, user_id: int) -> str | None:
        return await bot.db.get_lastfm_color(user_id)

    @staticmethod
    async def set_color(bot: Vain, user_id: int, color: str | None) -> None:
        await bot.db.set_lastfm_color(user_id, color)

    @staticmethod
    async def get_mode(bot: Vain, user_id: int) -> str | None:
        return await bot.db.get_lastfm_mode(user_id)

    @staticmethod
    async def set_mode(bot: Vain, user_id: int, mode: str | None) -> None:
        await bot.db.set_lastfm_mode(user_id, mode)

    @staticmethod
    async def get_reactions(bot: Vain, user_id: int) -> dict | None:
        return await bot.db.get_lastfm_reactions(user_id)

    @staticmethod
    async def set_reactions(bot: Vain, user_id: int, upvote: str | None, downvote: str | None) -> None:
        await bot.db.set_lastfm_reactions(user_id, upvote, downvote)

    @staticmethod
    async def get_custom_embed(bot: Vain, user_id: int) -> str | None:
        return await bot.db.get_lastfm_custom_embed(user_id)

    @staticmethod
    async def get_custom_embed_settings(bot: Vain, user_id: int) -> tuple[str | None, bool]:
        return await bot.db.get_lastfm_custom_embed_settings(user_id)

    @staticmethod
    async def set_custom_embed(bot: Vain, user_id: int, script: str | None, *, np_reply: bool = False) -> None:
        await bot.db.set_lastfm_custom_embed(user_id, script, np_reply=np_reply)

    @staticmethod
    async def mark_login_used(bot: Vain, token: str) -> None:
        await bot.db.mark_lastfm_login_used(token)

    
    
    

    @staticmethod
    async def get_guild_reactions(bot: Vain, guild_id: int) -> dict | None:
        return await bot.db.get_lastfm_guild_reactions(guild_id)

    @staticmethod
    async def set_guild_reactions(bot: Vain, guild_id: int, upvote: str | None, downvote: str | None) -> None:
        await bot.db.set_lastfm_guild_reactions(guild_id, upvote, downvote)

    @staticmethod
    async def get_custom_command(bot: Vain, guild_id: int, user_id: int) -> dict | None:
        return await bot.db.get_lastfm_custom_command(guild_id, user_id)

    @staticmethod
    async def set_custom_command(bot: Vain, guild_id: int, user_id: int, command: str) -> None:
        await bot.db.set_lastfm_custom_command(guild_id, user_id, command)

    @staticmethod
    async def remove_custom_command(bot: Vain, guild_id: int, user_id: int) -> None:
        await bot.db.remove_lastfm_custom_command(guild_id, user_id)

    @staticmethod
    async def list_custom_commands(bot: Vain, guild_id: int) -> list[dict]:
        return await bot.db.list_lastfm_custom_commands(guild_id)

    @staticmethod
    async def reset_custom_commands(bot: Vain, guild_id: int) -> None:
        await bot.db.reset_lastfm_custom_commands(guild_id)

    @staticmethod
    async def set_custom_public(bot: Vain, guild_id: int, user_id: int, public: bool) -> None:
        await bot.db.set_lastfm_custom_public(guild_id, user_id, public)

    @staticmethod
    async def list_blacklist(bot: Vain, guild_id: int) -> list[int]:
        return await bot.db.list_lastfm_blacklist(guild_id)

    @staticmethod
    async def set_blacklist(bot: Vain, guild_id: int, user_id: int) -> None:
        await bot.db.set_lastfm_blacklist(guild_id, user_id)

    @staticmethod
    async def remove_blacklist(bot: Vain, guild_id: int, user_id: int) -> None:
        await bot.db.remove_lastfm_blacklist(guild_id, user_id)

    @staticmethod
    async def list_hidden(bot: Vain, guild_id: int) -> list[int]:
        return await bot.db.list_lastfm_hidden(guild_id)

    @staticmethod
    async def set_hidden(bot: Vain, guild_id: int, user_id: int) -> None:
        await bot.db.set_lastfm_hidden(guild_id, user_id)

    @staticmethod
    async def remove_hidden(bot: Vain, guild_id: int, user_id: int) -> None:
        await bot.db.remove_lastfm_hidden(guild_id, user_id)


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
