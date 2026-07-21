from __future__ import annotations

import re
from logging import getLogger
from typing import Any, TypedDict

import discord
from discord import (
    ActivityType,
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


_NOTIFY_COOLDOWN_SEC = 30

_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")

_SLASH_RE = re.compile(r"[／⁄∕／]")


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
        if isinstance(ch, (TextChannel, Thread)):
            return ch
        
        ch = self.bot.get_channel(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def roles(self) -> list[Role]:
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
    def grantable_roles(self) -> list[Role]:
        """Roles we should attempt to grant (prefer assignable, fall back to all)."""
        assignable = self.assignable_roles
        return assignable if assignable else list(self.roles)

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
        # Never serve a stale channel_id after ,vanity channel ...
        row = await bot.db.fetchrow(
            "SELECT * FROM vanity WHERE guild_id = $1",
            guild.id,
            cached=False,
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
            cached=False,
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

    async def dispatch(self, member: Member) -> Message | None:
        """Send notification when a member starts repping vanity."""
        channel = self.channel
        if not channel:
            logger.warning(
                "vanity dispatch skipped: no channel guild=%s channel_id=%s",
                self.guild.id,
                self.channel_id,
            )
            return None

        redis = getattr(self.bot, "redis", None)
        key = f"notifs.vanity:{self.guild.id}-{member.id}"
        if redis is not None:
            try:
                
                if await redis.ratelimited(key, 1, _NOTIFY_COOLDOWN_SEC):
                    logger.debug("vanity dispatch cooldown %s", key)
                    return None
            except Exception:
                pass

        from core.tools.embed import Script

        template = self.template or self._default_template
        vanity_code = (self.guild.vanity_url_code or "vanity").lstrip("/")
        reward_role = (
            self.assignable_roles[0]
            if self.assignable_roles
            else (self.roles[0] if self.roles else None)
        )
        allowed = discord.AllowedMentions(users=True, roles=False, everyone=False)

        try:
            script = Script(template, user=member)
            rendered = script.render(
                user=member,
                member=member,
                guild=self.guild,
                channel=channel,
                vanity=vanity_code,
                vanity_role=reward_role,
            )
            
            rendered = rendered.replace("{user.mention}", member.mention)
            rendered = rendered.replace("{user}", member.mention)
            rendered = rendered.replace("{member.mention}", member.mention)
            rendered = rendered.replace("{member}", member.mention)

            if not rendered.strip():
                rendered = f"thank you {member.mention} for repping /{vanity_code}"

            
            if "{embed}" in template.lower() or "$v{" in template:
                msg = await script.send(
                    channel,
                    user=member,
                    member=member,
                    guild=self.guild,
                    channel=channel,
                    vanity=vanity_code,
                    vanity_role=reward_role,
                    allowed_mentions=allowed,
                )
            else:
                msg = await channel.send(content=rendered, allowed_mentions=allowed)

            logger.info(
                "vanity notify guild=%s member=%s channel=%s content=%r",
                self.guild.id,
                member.id,
                channel.id,
                rendered[:120],
            )
            return msg
        except HTTPException as exc:
            logger.warning(
                "vanity dispatch HTTP failed guild=%s channel=%s: %s",
                self.guild.id,
                getattr(channel, "id", None),
                exc,
            )
            return None
        except Exception as exc:
            logger.exception(
                "vanity dispatch error guild=%s: %s", self.guild.id, exc
            )
            
            try:
                return await channel.send(
                    content=f"thank you {member.mention} for repping /{vanity_code}",
                    allowed_mentions=allowed,
                )
            except Exception:
                return None


def get_status(member: Member) -> str:
    """Collect custom status / activity text for vanity matching.

    Discord stores custom status as type Custom with name often ``Custom Status``
    and the real text in ``state``. We also fall back to ``str(activity)``.
    """
    parts: list[str] = []
    activities = list(getattr(member, "activities", None) or ())

    primary = getattr(member, "activity", None)
    if primary is not None and primary not in activities:
        activities.insert(0, primary)

    for activity in activities:
        if activity is None:
            continue
        atype = getattr(activity, "type", None)
        is_custom = (
            isinstance(activity, CustomActivity)
            or atype is ActivityType.custom
            or getattr(atype, "name", None) == "custom"
            or int(getattr(atype, "value", -1)) == 4
        )
        if is_custom:
            for attr in ("state", "name", "details"):
                val = getattr(activity, attr, None)
                if not val:
                    continue
                text = str(val).strip()
                if not text or text.lower() in {"custom status", "customstatus"}:
                    continue
                parts.append(text)
            try:
                as_str = str(activity).strip()
                if as_str and as_str.lower() not in {"custom status", "customstatus"}:
                    parts.append(as_str)
            except Exception:
                pass
            continue

        for attr in ("name", "state", "details"):
            val = getattr(activity, attr, None)
            if val:
                parts.append(str(val))

    seen: set[str] = set()
    clean: list[str] = []
    for p in parts:
        p = _INVISIBLE_RE.sub("", p).strip()
        if not p:
            continue
        low = p.lower()
        if low not in seen:
            seen.add(low)
            clean.append(p)
    return " ".join(clean).lower()


def vanity_matches(status: str, code: str, *, strict: bool = False) -> bool:
    """Whether *status* is considered repping *code*."""
    if not code:
        return False
    status = _INVISIBLE_RE.sub("", (status or "")).lower()
    status = _SLASH_RE.sub("/", status)
    code = _INVISIBLE_RE.sub("", code).lower().lstrip("/").strip()
    if not status or not code:
        return False

    normalized = (
        status.replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .replace("discord.gg/", "/")
        .replace("discord.com/invite/", "/")
        .replace("discordapp.com/invite/", "/")
        .replace(".gg/", "/")
    )
    
    normalized = re.sub(r"/\s+", "/", normalized)
    status_ns = re.sub(r"\s+", "", status)
    normalized_ns = re.sub(r"\s+", "", normalized)

    if not strict:
        needles = (code, f"/{code}", f".gg/{code}")
        haystacks = (status, normalized, status_ns, normalized_ns)
        return any(n in h for n in needles for h in haystacks)

    patterns = (
        rf"(?:^|[\s])/{re.escape(code)}(?:\b|$)",
        rf"(?:^|[\s/]){re.escape(code)}(?:\b|$)",
        rf"discord\.gg/{re.escape(code)}\b",
        rf"\.gg/{re.escape(code)}\b",
        rf"discord\.com/invite/{re.escape(code)}\b",
    )
    return any(re.search(p, status) or re.search(p, normalized) for p in patterns)


def member_repping_vanity(member: Member, guild: Guild, *, strict: bool = False) -> bool:
    code = (guild.vanity_url_code or "").lower()
    if not code:
        return False
    return vanity_matches(get_status(member), code, strict=strict)


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
    "member_repping_vanity",
    "fetch",
    "upsert",
    "insert",
]
