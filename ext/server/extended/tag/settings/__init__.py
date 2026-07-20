from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict

from discord import Guild, HTTPException, Member, Message, Role, TextChannel, Thread

from core.vain import Vain

logger = getLogger("vain.server.extended.tag.settings")


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
        return "thank you {user.mention} for repping the server tag"

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
            "SELECT * FROM guild_tag WHERE guild_id = $1",
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
                "ALTER TABLE guild_tag ADD COLUMN IF NOT EXISTS strict BOOLEAN NOT NULL DEFAULT FALSE"
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
        INSERT INTO guild_tag (guild_id, channel_id, role_ids, template, strict)
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
            logger.debug("upsert guild_tag guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM guild_tag WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    async def dispatch(self, before: Member, member: Member) -> Message | None:
        channel = self.channel
        if not channel:
            return None
        redis = getattr(self.bot, "redis", None)
        key = f"notifs.tag:{self.guild.id}-{member.id}"
        if redis is not None:
            try:
                if await redis.ratelimited(key, 1, 3 * 3600):
                    return None
            except Exception:
                pass
        from core.tools.embed import Script

        pg = getattr(member, "primary_guild", None)
        tag = getattr(pg, "tag", None) if pg else None
        template = (self.template or self._default_template).replace(
            "{tag}", str(tag or "tag")
        )
        script = Script(template, user=member)
        try:
            return await script.send(
                channel,
                user=member,
                guild=self.guild,
                channel=channel,
                role=self.assignable_roles[0]
                if self.assignable_roles
                else (self.roles[0] if self.roles else None),
            )
        except HTTPException as exc:
            logger.warning("tag dispatch failed guild=%s: %s", self.guild.id, exc)
            return None
        except Exception as exc:
            logger.exception("tag dispatch error guild=%s: %s", self.guild.id, exc)
            return None


def member_repping_tag(
    member: Member, guild: Guild, *, strict: bool = False
) -> bool:
    """Whether *member* is displaying this guild as their primary guild tag."""
    pg = getattr(member, "primary_guild", None)
    if pg is None:
        return False
    gid = getattr(pg, "id", None)
    if gid is None or int(gid) != int(guild.id):
        return False
    enabled = getattr(pg, "identity_enabled", None)
    if strict:
        # Must have explicitly reaffirmed identity display
        return enabled is True
    # Loose: True or None (public guild pending reaffirm) both count
    return enabled is not False


def tag_label(member: Member) -> str | None:
    pg = getattr(member, "primary_guild", None)
    return getattr(pg, "tag", None) if pg else None


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
    "member_repping_tag",
    "tag_label",
    "fetch",
    "upsert",
    "insert",
]
