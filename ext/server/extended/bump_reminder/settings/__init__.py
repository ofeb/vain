from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any, TypedDict

from discord import Guild, Role, TextChannel, Thread

from core.vain import Vain

logger = getLogger("vain.bump_reminder.settings")

_ENSURED = False


class Record(TypedDict, total=False):
    """DB row for `bump_reminder`."""

    guild_id: int
    channel_id: Any | None
    role_id: Any | None
    message: Any | None
    thankyou_message: Any | None
    last_bump_at: Any | None
    next_bump_at: Any | None
    last_bumper_id: Any | None
    bump_channel_id: Any | None
    enabled: bool


class Settings:
    """Guild settings for `bump_reminder`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get("enabled")) and bool(self.record.get("channel_id"))

    @property
    def channel_id(self) -> Any | None:
        return self.record.get("channel_id")

    @property
    def role_id(self) -> Any | None:
        return self.record.get("role_id")

    @property
    def message(self) -> Any | None:
        return self.record.get("message")

    @property
    def thankyou_message(self) -> Any | None:
        return self.record.get("thankyou_message")

    @property
    def last_bump_at(self) -> Any | None:
        return self.record.get("last_bump_at")

    @property
    def next_bump_at(self) -> Any | None:
        return self.record.get("next_bump_at")

    @property
    def last_bumper_id(self) -> Any | None:
        return self.record.get("last_bumper_id")

    @property
    def bump_channel_id(self) -> Any | None:
        return self.record.get("bump_channel_id")

    @property
    def enabled(self) -> bool:
        return bool(self.record.get("enabled", False))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get("channel_id")
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def role(self) -> Role | None:
        rid = self.record.get("role_id")
        if not rid:
            return None
        return self.guild.get_role(int(rid))

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            "channel_id": None,
            "role_id": None,
            "message": None,
            "thankyou_message": None,
            "last_bump_at": None,
            "next_bump_at": None,
            "last_bumper_id": None,
            "bump_channel_id": None,
            "enabled": False,
        }

    @classmethod
    async def ensure_table(cls, bot: Vain) -> None:
        global _ENSURED
        if _ENSURED:
            return
        if getattr(bot.db, "pool", None) is None:
            return
        with contextlib.suppress(Exception):
            await bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS bump_reminder (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT,
                    role_id BIGINT,
                    message TEXT,
                    thankyou_message TEXT,
                    last_bump_at TIMESTAMPTZ,
                    next_bump_at TIMESTAMPTZ,
                    last_bumper_id BIGINT,
                    bump_channel_id BIGINT,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            for col, typ in (
                ("thankyou_message", "TEXT"),
                ("last_bump_at", "TIMESTAMPTZ"),
                ("next_bump_at", "TIMESTAMPTZ"),
                ("last_bumper_id", "BIGINT"),
                ("bump_channel_id", "BIGINT"),
            ):
                with contextlib.suppress(Exception):
                    await bot.db.execute(
                        f"ALTER TABLE bump_reminder ADD COLUMN IF NOT EXISTS {col} {typ}"
                    )
            _ENSURED = True

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        await cls.ensure_table(bot)
        row = await bot.db.fetchrow(
            "SELECT * FROM bump_reminder WHERE guild_id = $1",
            guild.id,
        )
        if row is None:
            data = cls._default_config()
            data["guild_id"] = guild.id
            return cls(bot, guild, data)
        return cls(bot, guild, dict(row))

    @classmethod
    async def exists(cls, bot: Vain, guild: Guild) -> bool:
        await cls.ensure_table(bot)
        return bool(
            await bot.db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bump_reminder WHERE guild_id = $1)",
                guild.id,
            )
        )

    @classmethod
    async def fetch_all_enabled(cls, bot: Vain) -> list[dict[str, Any]]:
        await cls.ensure_table(bot)
        if getattr(bot.db, "pool", None) is None:
            return []
        rows = await bot.db.fetch(
            """
            SELECT * FROM bump_reminder
            WHERE enabled = TRUE AND channel_id IS NOT NULL
            """
        )
        return [dict(r) for r in (rows or [])]

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        await self.ensure_table(self.bot)
        keys = (
            "channel_id",
            "role_id",
            "message",
            "thankyou_message",
            "last_bump_at",
            "next_bump_at",
            "last_bumper_id",
            "bump_channel_id",
            "enabled",
        )
        values: dict[str, Any] = {"guild_id": self.guild.id}
        for key in keys:
            if key in kwargs:
                values[key] = kwargs[key]
            else:
                values[key] = self.record.get(key)

        query = """
        INSERT INTO bump_reminder (
            guild_id, channel_id, role_id, message, thankyou_message,
            last_bump_at, next_bump_at, last_bumper_id, bump_channel_id, enabled
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            role_id = EXCLUDED.role_id,
            message = EXCLUDED.message,
            thankyou_message = EXCLUDED.thankyou_message,
            last_bump_at = EXCLUDED.last_bump_at,
            next_bump_at = EXCLUDED.next_bump_at,
            last_bumper_id = EXCLUDED.last_bumper_id,
            bump_channel_id = EXCLUDED.bump_channel_id,
            enabled = EXCLUDED.enabled
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values["guild_id"],
            values.get("channel_id"),
            values.get("role_id"),
            values.get("message"),
            values.get("thankyou_message"),
            values.get("last_bump_at"),
            values.get("next_bump_at"),
            values.get("last_bumper_id"),
            values.get("bump_channel_id"),
            bool(values.get("enabled")),
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug(
                "upsert bump_reminder guild=%s keys=%s",
                self.guild.id,
                list(kwargs),
            )
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.ensure_table(self.bot)
        await self.bot.db.execute(
            "DELETE FROM bump_reminder WHERE guild_id = $1",
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
