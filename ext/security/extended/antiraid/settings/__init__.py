from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread

from core.vain import Vain

logger = getLogger('vain.antiraid.settings')


class Record(TypedDict, total=False):
    """DB row for `antiraid_config`."""

    guild_id: int
    raid_active: bool
    punish_until: Any | None


class Settings:
    """Guild settings for `antiraid_config`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return True

    @property
    def raid_active(self) -> bool:
        return bool(self.record.get('raid_active', False))

    @property
    def punish_until(self) -> Any | None:
        return self.record.get('punish_until')

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'raid_active': False,
            'punish_until': None,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM antiraid_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM antiraid_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'raid_active': kwargs.get('raid_active', self.raid_active),
            'punish_until': kwargs.get('punish_until', self.punish_until),
        }
        query = """
        INSERT INTO antiraid_config (guild_id, raid_active, punish_until)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id) DO UPDATE SET
            raid_active = EXCLUDED.raid_active,
            punish_until = EXCLUDED.punish_until
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['raid_active'],
            values['punish_until'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert antiraid_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM antiraid_config WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    async def fetch_modules(self) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetch(
            "SELECT * FROM antiraid_modules WHERE guild_id = $1",
            self.guild.id,
        )
        return [dict(r) for r in rows]

    async def upsert_module(self, module: str, **fields: Any) -> dict[str, Any]:
        row = await self.bot.db.fetchrow(
            "SELECT * FROM antiraid_modules WHERE guild_id = $1 AND module = $2",
            self.guild.id,
            module,
        )
        data = dict(row) if row else {
            "guild_id": self.guild.id,
            "module": module,
            "enabled": False,
            "threshold": 5,
            "action": "ban",
            "lock_channels": False,
            "punish_new": False,
        }
        data.update(fields)
        data["guild_id"] = self.guild.id
        data["module"] = module
        await self.bot.db.execute(
            """
            INSERT INTO antiraid_modules (
                guild_id, module, enabled, threshold, action, lock_channels, punish_new
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, module) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                threshold = EXCLUDED.threshold,
                action = EXCLUDED.action,
                lock_channels = EXCLUDED.lock_channels,
                punish_new = EXCLUDED.punish_new
            """,
            data["guild_id"],
            data["module"],
            data.get("enabled", False),
            data.get("threshold", 5),
            data.get("action", "ban"),
            data.get("lock_channels", False),
            data.get("punish_new", False),
        )
        return data


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
