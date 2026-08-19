from __future__ import annotations

import contextlib
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

    @staticmethod
    async def ensure_schema(db: Any) -> None:
        if getattr(db, "pool", None) is None:
            return
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS message_rolegain TEXT DEFAULT NULL"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS channel_id BIGINT"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS stack BOOLEAN DEFAULT FALSE"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS command BOOLEAN DEFAULT FALSE"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS roles TEXT DEFAULT '[]'"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS channels TEXT DEFAULT '[]'"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS users TEXT DEFAULT '[]'"
            )

    @staticmethod
    async def get_cfg(db: Any, guild_id: int) -> dict | None:
        row = await db.fetchrow(
            "SELECT * FROM leveling WHERE guild_id = $1", guild_id
        )
        return dict(row) if row else None

    @staticmethod
    async def get_level_user(db: Any, guild_id: int, user_id: int) -> dict | None:
        row = await db.fetchrow(
            "SELECT * FROM level_user WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def fetch_all_level_users(db: Any, guild_id: int) -> list[dict]:
        rows = await db.fetch(
            "SELECT * FROM level_user WHERE guild_id = $1", guild_id
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def enable_guild(db: Any, guild_id: int) -> None:
        await db.execute(
            "UPDATE leveling SET enabled = TRUE WHERE guild_id = $1",
            guild_id,
        )

    @staticmethod
    async def create_guild(db: Any, guild_id: int, message: str) -> None:
        await db.execute(
            """INSERT INTO leveling
               (guild_id, message, multiplier, booster, stack, command, enabled)
               VALUES ($1, $2, 1.0, 1.0, false, false, true)""",
            guild_id,
            message,
        )

    @staticmethod
    async def disable_guild(db: Any, guild_id: int) -> None:
        await db.execute(
            "UPDATE leveling SET enabled = FALSE WHERE guild_id = $1",
            guild_id,
        )

    @staticmethod
    async def set_channel(db: Any, channel_id: int | None, guild_id: int) -> None:
        await db.execute(
            "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
            channel_id,
            guild_id,
        )

    @staticmethod
    async def set_message(db: Any, column: str, script: str, guild_id: int) -> None:
        await db.execute(
            f"UPDATE leveling SET {column} = $1 WHERE guild_id = $2",
            script,
            guild_id,
        )

    @staticmethod
    async def set_multiplier(db: Any, value: float, guild_id: int) -> None:
        await db.execute(
            "UPDATE leveling SET multiplier = $1 WHERE guild_id = $2",
            value,
            guild_id,
        )

    @staticmethod
    async def set_booster(db: Any, value: float, guild_id: int) -> None:
        await db.execute(
            "UPDATE leveling SET booster = $1 WHERE guild_id = $2",
            value,
            guild_id,
        )

    @staticmethod
    async def set_user_level(db: Any, guild_id: int, user_id: int, level: int, target_xp: int) -> None:
        await db.execute(
            """INSERT INTO level_user (guild_id, user_id, xp, level, target_xp)
               VALUES ($1, $2, 0, $3, $4)
               ON CONFLICT (guild_id, user_id)
               DO UPDATE SET xp = 0, level = $3, target_xp = $4""",
            guild_id,
            user_id,
            level,
            target_xp,
        )

    @staticmethod
    async def reset_user(db: Any, guild_id: int, user_id: int) -> None:
        await db.execute(
            "DELETE FROM level_user WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    @staticmethod
    async def reset_all_users(db: Any, guild_id: int) -> None:
        await db.execute(
            "DELETE FROM level_user WHERE guild_id = $1", guild_id
        )

    @staticmethod
    async def wipe_guild(db: Any, guild_id: int) -> None:
        await db.execute(
            "DELETE FROM leveling WHERE guild_id = $1", guild_id
        )
        await db.execute(
            "DELETE FROM level_user WHERE guild_id = $1", guild_id
        )
        with contextlib.suppress(Exception):
            await db.execute(
                "DELETE FROM level_rewards WHERE guild_id = $1", guild_id
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "DELETE FROM level_multiplier WHERE guild_id = $1", guild_id
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "DELETE FROM level_multiplier_voice WHERE guild_id = $1", guild_id
            )

    @staticmethod
    async def get_reward_for_role(db: Any, guild_id: int, role_id: int) -> dict | None:
        row = await db.fetchrow(
            "SELECT level FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            guild_id,
            role_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def add_reward(db: Any, guild_id: int, level: int, role_id: int) -> None:
        await db.execute(
            "INSERT INTO level_rewards (guild_id, level, role_id) VALUES ($1, $2, $3)",
            guild_id,
            level,
            role_id,
        )

    @staticmethod
    async def remove_reward(db: Any, guild_id: int, role_id: int) -> None:
        await db.execute(
            "DELETE FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            guild_id,
            role_id,
        )

    @staticmethod
    async def fetch_rewards(db: Any, guild_id: int) -> list[dict]:
        rows = await db.fetch(
            "SELECT role_id, level FROM level_rewards WHERE guild_id = $1 ORDER BY level",
            guild_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def fetch_rewards_up_to_level(db: Any, guild_id: int, level: int) -> list[dict]:
        rows = await db.fetch(
            "SELECT role_id, level FROM level_rewards WHERE guild_id = $1 AND level <= $2",
            guild_id,
            level,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def set_stack(db: Any, enabled: bool, guild_id: int) -> None:
        await db.execute(
            "UPDATE leveling SET stack = $1 WHERE guild_id = $2",
            enabled,
            guild_id,
        )

    @staticmethod
    async def update_ignore(db: Any, column: str, value: str, guild_id: int) -> None:
        await db.execute(
            f"UPDATE leveling SET {column} = $1 WHERE guild_id = $2",
            value,
            guild_id,
        )


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


__all__ = ["Settings", "Record", "fetch"]
