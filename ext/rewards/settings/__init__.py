from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.leveling.settings")


class Record(TypedDict, total=False):
    guild_id: int
    message: str | None
    channel_id: int | None
    multiplier: float
    booster: float
    voice_multiplier: float
    voice_booster: float
    stack: bool
    command: bool
    roles: str
    channels: str
    users: str
    enabled: bool


class Settings:
    """Guild leveling settings backed by the `leveling` table."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get("guild_id")) and self.enabled

    @property
    def enabled(self) -> bool:
        if not self.record.get("guild_id"):
            return False
        if "enabled" not in self.record:
            return True
        return bool(self.record.get("enabled"))

    @property
    def multiplier(self) -> float:
        return float(self.record.get("multiplier") or 1.0)

    @property
    def booster(self) -> float:
        return float(self.record.get("booster") or 1.0)

    @property
    def message(self) -> str | None:
        return self.record.get("message")

    @property
    def channel_id(self) -> int | None:
        return self.record.get("channel_id")

    @property
    def stack(self) -> bool:
        return bool(self.record.get("stack"))

    @property
    def ignore_commands(self) -> bool:
        return bool(self.record.get("command"))

    @staticmethod
    def _default_config(guild_id: int = 0) -> dict[str, Any]:
        return {
            "guild_id": guild_id,
            "message": "Nice work {user.mention} - you reached **Level {level}**!",
            "channel_id": None,
            "multiplier": 1.0,
            "booster": 1.0,
            "voice_multiplier": 1.0,
            "voice_booster": 1.0,
            "stack": False,
            "command": False,
            "roles": "[]",
            "channels": "[]",
            "users": "[]",
            "enabled": False,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM leveling WHERE guild_id = $1",
            guild.id,
        )
        if row is None:
            return cls(bot, guild, cls._default_config(0))  
        return cls(bot, guild, dict(row))

    @classmethod
    async def exists(cls, bot: Vain, guild: Guild) -> bool:
        return bool(
            await bot.db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM leveling WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        
        if not await self.exists(self.bot, self.guild):
            return self
        
        if not kwargs:
            return self
        cols = []
        vals = []
        i = 1
        for k, v in kwargs.items():
            cols.append(f"{k} = ${i}")
            vals.append(v)
            i += 1
        vals.append(self.guild.id)
        query = f"UPDATE leveling SET {', '.join(cols)} WHERE guild_id = ${i} RETURNING *"
        record = await self.bot.db.fetchrow(query, *vals)
        if record is not None:
            self.record = dict(record)
        if revalidate:
            logger.debug("upsert leveling guild=%s keys=%s", self.guild.id, list(kwargs))
        return self


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


__all__ = ["Settings", "Record", "fetch"]
