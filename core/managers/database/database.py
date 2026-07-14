from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Guild:
    guild_id: int
    prefix: str = ","
    language: str = "en"
    muted_role_id: Optional[int] = None
    auto_role_id: Optional[int] = None
    welcome_channel_id: Optional[int] = None
    welcome_message: Optional[str] = None
    leave_channel_id: Optional[int] = None
    leave_message: Optional[str] = None
    boost_channel_id: Optional[int] = None
    boost_message: Optional[str] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class User:
    user_id: int
    guild_id: int
    balance: int = 0
    xp: int = 0
    level: int = 0
    warnings: int = 0
    muted_until: Optional[datetime] = None
    birthday: Optional[str] = None
    timezone: Optional[str] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()


@dataclass
class Moderation:
    id: Optional[int] = None
    guild_id: int = 0
    user_id: int = 0
    moderator_id: int = 0
    action_type: str = ""
    reason: str = ""
    duration: Optional[str] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Highlight:
    guild_id: int
    user_id: int
    keyword: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class HighlightIgnore:
    guild_id: int
    user_id: int
    target_id: int
    target_type: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class StickyRole:
    guild_id: int
    user_id: int
    role_id: int
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Forcenickname:
    guild_id: int
    user_id: int
    nickname: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class RestrictCommand:
    guild_id: int
    command_name: str
    role_id: int
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class RobloxLink:
    discord_id: int
    roblox_id: int
    username: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class SnapchatLink:
    discord_id: int
    snapchat_username: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Reminder:
    user_id: int
    guild_id: int
    message: str
    time: datetime
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Note:
    guild_id: int
    user_id: int
    moderator_id: int
    content: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Proof:
    guild_id: int
    user_id: int
    moderator_id: int
    case_id: int
    url: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class DatabaseManager:
    def __init__(self, pool):
        self.pool = pool

    async def get_guild(self, guild_id: int) -> Optional[Guild]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guilds WHERE guild_id = $1",
                guild_id
            )
            return Guild(**dict(row)) if row else None

    async def create_guild(self, guild: Guild) -> Guild:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO guilds 
                   (guild_id, prefix, language, muted_role_id, auto_role_id, 
                    welcome_channel_id, welcome_message, leave_channel_id, 
                    leave_message, boost_channel_id, boost_message, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                   ON CONFLICT (guild_id) DO UPDATE SET
                    prefix = EXCLUDED.prefix,
                    language = EXCLUDED.language,
                    muted_role_id = EXCLUDED.muted_role_id,
                    auto_role_id = EXCLUDED.auto_role_id,
                    welcome_channel_id = EXCLUDED.welcome_channel_id,
                    welcome_message = EXCLUDED.welcome_message,
                    leave_channel_id = EXCLUDED.leave_channel_id,
                    leave_message = EXCLUDED.leave_message,
                    boost_channel_id = EXCLUDED.boost_channel_id,
                    boost_message = EXCLUDED.boost_message""",
                guild.guild_id, guild.prefix, guild.language, guild.muted_role_id,
                guild.auto_role_id, guild.welcome_channel_id, guild.welcome_message,
                guild.leave_channel_id, guild.leave_message, guild.boost_channel_id,
                guild.boost_message, guild.created_at
            )
        return guild

    async def get_user(self, user_id: int, guild_id: int) -> Optional[User]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            return User(**dict(row)) if row else None

    async def create_user(self, user: User) -> User:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users 
                   (user_id, guild_id, balance, xp, level, warnings, 
                    muted_until, birthday, timezone, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                   ON CONFLICT (user_id, guild_id) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    xp = EXCLUDED.xp,
                    level = EXCLUDED.level,
                    warnings = EXCLUDED.warnings,
                    muted_until = EXCLUDED.muted_until,
                    birthday = EXCLUDED.birthday,
                    timezone = EXCLUDED.timezone,
                    updated_at = EXCLUDED.updated_at""",
                user.user_id, user.guild_id, user.balance, user.xp, user.level,
                user.warnings, user.muted_until, user.birthday, user.timezone,
                user.created_at, user.updated_at
            )
        return user

    async def add_moderation(self, moderation: Moderation) -> Moderation:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO moderation 
                   (guild_id, user_id, moderator_id, action_type, reason, duration, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   RETURNING id""",
                moderation.guild_id, moderation.user_id, moderation.moderator_id,
                moderation.action_type, moderation.reason, moderation.duration,
                moderation.created_at
            )
            moderation.id = row['id']
        return moderation

    async def get_moderation_history(self, guild_id: int, user_id: int, limit: int = 10):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM moderation 
                   WHERE guild_id = $1 AND user_id = $2 
                   ORDER BY created_at DESC LIMIT $3""",
                guild_id, user_id, limit
            )
            return [Moderation(**dict(row)) for row in rows]

    async def add_highlight(self, highlight: Highlight) -> Highlight:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO highlights 
                   (guild_id, user_id, keyword, created_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (guild_id, user_id, keyword) DO NOTHING""",
                highlight.guild_id, highlight.user_id, highlight.keyword, highlight.created_at
            )
        return highlight

    async def remove_highlight(self, guild_id: int, user_id: int, keyword: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                guild_id, user_id, keyword
            )

    async def get_highlights(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM highlights WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id
            )
            return [Highlight(**dict(row)) for row in rows]

    async def add_sticky_role(self, sticky_role: StickyRole) -> StickyRole:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO sticky_roles 
                   (guild_id, user_id, role_id, created_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (guild_id, user_id, role_id) DO NOTHING""",
                sticky_role.guild_id, sticky_role.user_id, sticky_role.role_id,
                sticky_role.created_at
            )
        return sticky_role

    async def get_sticky_roles(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM sticky_roles WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id
            )
            return [StickyRole(**dict(row)) for row in rows]
