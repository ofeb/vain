from __future__ import annotations

import re
from logging import getLogger
from typing import Any, TypedDict

from discord import (
    CustomActivity,
    Guild,
    HTTPException,
    Member,
    Message,
    Role,
    TextChannel,
    Thread,
)

from core.vain import Vain

logger = getLogger("vain.server.extended.vanity.settings")


class Record(TypedDict, total=False):
    guild_id: int
    channel_id: Any | None
    role_ids: list[Any]
    template: Any | None
    strict: bool


class Settings:
    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.role_ids or self.channel_id)

    @property
    def channel_id(self) -> Any | None:
        return self.record.get("channel_id")

    @property
    def role_ids(self) -> list[int]:
        out: list[int] = []
        for rid in self.record.get("role_ids") or []:
            try:
                out.append(int(rid))
            except (TypeError, ValueError):
                continue
        return out

    @property
    def template(self) -> str | None:
        val = self.record.get("template")
        return str(val) if val else None

    @property
    def strict(self) -> bool:
        return bool(self.record.get("strict", False))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get("channel_id")
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def roles(self) -> list[Role]:
        """All configured roles that still exist (for display)."""
        out: list[Role] = []
        for rid in self.role_ids:
            role = self.guild.get_role(int(rid))
            if role is not None:
                out.append(role)
        return out

    @property
    def assignable_roles(self) -> list[Role]:
        return [r for r in self.roles if r.is_assignable()]

    @property
    def _default_template(self) -> str:
        code = self.guild.vanity_url_code or "vanity"
        return f"thank you {{user.mention}} for repping /{code}"

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            "channel_id": None,
            "role_ids": [],
            "template": None,
            "strict": False,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        await cls._ensure_schema(bot)
        row = await bot.db.fetchrow(
            "SELECT * FROM vanity WHERE guild_id = $1",
            guild.id,
        )
        if row is None:
            data = cls._default_config()
            data["guild_id"] = guild.id
            return cls(bot, guild, data)
        return cls(bot, guild, dict(row))

    @staticmethod
    async def _ensure_schema(bot: Vain) -> None:
        try:
            await bot.db.execute(
                "ALTER TABLE vanity ADD COLUMN IF NOT EXISTS strict BOOLEAN NOT NULL DEFAULT FALSE"
            )
        except Exception:
            pass

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        await self._ensure_schema(self.bot)
        values = {
            "guild_id": self.guild.id,
            "channel_id": kwargs.get("channel_id", self.channel_id),
            "role_ids": kwargs.get("role_ids", self.role_ids),
            "template": kwargs.get("template", self.template),
            "strict": kwargs.get("strict", self.strict),
        }
        query = """
        INSERT INTO vanity (guild_id, channel_id, role_ids, template, strict)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            role_ids = EXCLUDED.role_ids,
            template = EXCLUDED.template,
            strict = EXCLUDED.strict
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values["guild_id"],
            values["channel_id"],
            values["role_ids"],
            values["template"],
            bool(values["strict"]),
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert vanity guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM vanity WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    async def dispatch(self, before: Member, member: Member) -> Message | None:
        """Send notification when a member starts repping vanity."""
        channel = self.channel
        if not channel:
            return None
        redis = getattr(self.bot, "redis", None)
        key = f"notifs.vanity:{self.guild.id}-{member.id}"
        if redis is not None:
            try:
                if await redis.ratelimited(key, 1, 3 * 3600):
                    return None
            except Exception:
                pass
        from core.tools.embed import Script

        template = self.template or self._default_template
        script = Script(template, user=member)
        try:
            return await script.send(
                channel,
                user=member,
                guild=self.guild,
                channel=channel,
                role=self.assignable_roles[0] if self.assignable_roles else (
                    self.roles[0] if self.roles else None
                ),
            )
        except HTTPException as exc:
            logger.warning("vanity dispatch failed guild=%s: %s", self.guild.id, exc)
            return None
        except Exception as exc:
            logger.exception("vanity dispatch error guild=%s: %s", self.guild.id, exc)
            return None


def get_status(member: Member) -> str:
    """Collect custom status / activity text for vanity matching."""
    parts: list[str] = []
    for activity in member.activities or ():
        if isinstance(activity, CustomActivity):
            if activity.name:
                parts.append(str(activity.name))
            state = getattr(activity, "state", None)
            if state:
                parts.append(str(state))
        else:
            for attr in ("name", "state", "details"):
                val = getattr(activity, attr, None)
                if val:
                    parts.append(str(val))
    return " ".join(parts).lower()


def vanity_matches(status: str, code: str, *, strict: bool = False) -> bool:
    """Whether *status* is considered repping *code*."""
    if not code:
        return False
    status = (status or "").lower()
    code = code.lower().lstrip("/")
    if not status:
        return False
    if not strict:
        # Loose: vanity code appears anywhere
        return code in status
    # Strict: require /code, discord.gg/code, or .gg/code style tokens
    patterns = (
        rf"(?:^|[\s/])/{re.escape(code)}(?:\b|$)",
        rf"discord\.gg/{re.escape(code)}\b",
        rf"\.gg/{re.escape(code)}\b",
        rf"\b{re.escape(code)}\b",
    )
    return any(re.search(p, status) for p in patterns)


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = [
    "Settings",
    "Record",
    "get_status",
    "vanity_matches",
    "fetch",
    "upsert",
    "insert",
]
