from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild

from core.vain import Vain

logger = getLogger('vain.server.extended.prefix.settings')


class Record(TypedDict, total=False):
    """DB row for `config`."""

    guild_id: int
    prefixes: list[Any]
    colorme: bool
    colorme_base: Any | None
    lastfm_reactions: list[Any]


class Settings:
    """Guild settings for `config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get('prefixes'))

    @property
    def prefixes(self) -> list[Any]:
        return list(self.record.get('prefixes') or [])

    @property
    def colorme(self) -> bool:
        return bool(self.record.get('colorme', False))

    @property
    def colorme_base(self) -> Any | None:
        return self.record.get('colorme_base')

    @property
    def lastfm_reactions(self) -> list[Any]:
        return list(self.record.get('lastfm_reactions') or [])

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'prefixes': [','],
            'colorme': False,
            'colorme_base': None,
            'lastfm_reactions': [],
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'prefixes': kwargs.get('prefixes', self.prefixes),
            'colorme': kwargs.get('colorme', self.colorme),
            'colorme_base': kwargs.get('colorme_base', self.colorme_base),
            'lastfm_reactions': kwargs.get('lastfm_reactions', self.lastfm_reactions),
        }
        query = """
        INSERT INTO config (guild_id, prefixes, colorme, colorme_base, lastfm_reactions)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id) DO UPDATE SET
            prefixes = EXCLUDED.prefixes,
            colorme = EXCLUDED.colorme,
            colorme_base = EXCLUDED.colorme_base,
            lastfm_reactions = EXCLUDED.lastfm_reactions
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['prefixes'],
            values['colorme'],
            values['colorme_base'],
            values['lastfm_reactions'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM config WHERE guild_id = $1",
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
