from __future__ import annotations

from logging import getLogger
from typing import Any, Optional, TypedDict

from discord import Guild, TextChannel, Thread

from core.vain import Vain

logger = getLogger("vain.starboard.settings")


class Record(TypedDict, total=False):
    guild_id: int
    channel_id: int
    emoji: str
    threshold: int
    self_star: bool
    lock: bool
    ignore_entries: Any
    attachments: bool
    ts: bool
    jump: bool
    color: str | None


class Config:
    """One starboard binding: guild + emoji → channel + options."""

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    @property
    def emoji(self) -> str:
        return str(self.record.get("emoji") or "⭐")

    @property
    def threshold(self) -> int:
        return max(1, int(self.record.get("threshold") or 3))

    @property
    def self_star(self) -> bool:
        return bool(self.record.get("self_star", True))

    @property
    def lock(self) -> bool:
        return bool(self.record.get("lock", False))

    @property
    def channel_id(self) -> int | None:
        cid = self.record.get("channel_id")
        return int(cid) if cid else None

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.channel_id
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(cid)
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def color(self) -> str | None:
        return self.record.get("color")

    @property
    def attachments(self) -> bool:
        return bool(self.record.get("attachments", True))

    @property
    def ts(self) -> bool:
        return bool(self.record.get("ts", True))

    @property
    def jump(self) -> bool:
        return bool(self.record.get("jump", True))

    @property
    def ignore_entries(self) -> Any:
        return self.record.get("ignore_entries")

    @classmethod
    async def ensure_schema(cls, bot: Vain) -> None:
        """Create multi-emoji starboard tables if missing (safe IF NOT EXISTS)."""
        statements = [
            """
            CREATE TABLE IF NOT EXISTS starboard (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '⭐',
                threshold INT NOT NULL DEFAULT 3,
                self_star BOOLEAN NOT NULL DEFAULT TRUE,
                lock BOOLEAN NOT NULL DEFAULT FALSE,
                ignore_entries TEXT,
                attachments BOOLEAN NOT NULL DEFAULT TRUE,
                ts BOOLEAN NOT NULL DEFAULT TRUE,
                jump BOOLEAN NOT NULL DEFAULT TRUE,
                color TEXT,
                PRIMARY KEY (guild_id, emoji)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS starboard_entry (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                emoji TEXT NOT NULL,
                star_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, message_id, emoji)
            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS starboard_entries (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                emoji TEXT NOT NULL,
                starboard_message_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, message_id, emoji)
            )
            """,
        ]
        for sql in statements:
            try:
                await bot.db.execute(sql)
            except Exception as exc:
                logger.debug("starboard schema skip: %s", exc)

    @classmethod
    async def fetch_emoji(cls, bot: Vain, guild: Guild, emoji: str) -> Optional[Config]:
        row = await bot.db.fetchrow(
            "SELECT * FROM starboard WHERE guild_id = $1 AND emoji = $2",
            guild.id,
            str(emoji),
        )
        if row is None:
            return None
        return cls(bot, guild, dict(row))

    @classmethod
    async def fetch_all(cls, bot: Vain, guild: Guild) -> list[Config]:
        rows = await bot.db.fetch(
            "SELECT * FROM starboard WHERE guild_id = $1 ORDER BY emoji",
            guild.id,
        )
        return [cls(bot, guild, dict(r)) for r in rows or []]

    @classmethod
    async def upsert(
        cls,
        bot: Vain,
        guild: Guild,
        *,
        channel_id: int,
        emoji: str,
        threshold: int = 3,
        self_star: bool = True,
    ) -> Config:
        await cls.ensure_schema(bot)
        row = await bot.db.fetchrow(
            """
            INSERT INTO starboard (guild_id, channel_id, emoji, threshold, self_star)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id, emoji) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                threshold = EXCLUDED.threshold,
                self_star = EXCLUDED.self_star
            RETURNING *
            """,
            guild.id,
            channel_id,
            str(emoji),
            int(threshold),
            bool(self_star),
        )
        return cls(bot, guild, dict(row) if row else {
            "guild_id": guild.id,
            "channel_id": channel_id,
            "emoji": str(emoji),
            "threshold": threshold,
            "self_star": self_star,
        })

    @classmethod
    async def delete(
        cls, bot: Vain, guild: Guild, *, channel_id: int, emoji: str
    ) -> bool:
        result = await bot.db.execute(
            """
            DELETE FROM starboard
            WHERE guild_id = $1 AND channel_id = $2 AND emoji = $3
            """,
            guild.id,
            channel_id,
            str(emoji),
        )
        return str(result) != "DELETE 0"

    @classmethod
    async def clear(cls, bot: Vain, guild: Guild) -> int:
        result = await bot.db.execute(
            "DELETE FROM starboard WHERE guild_id = $1",
            guild.id,
        )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def get_star_message_id(self, message_id: int, channel_id: int) -> int | None:
        
        for table, col in (
            ("starboard_entry", "star_id"),
            ("starboard_entries", "starboard_message_id"),
        ):
            try:
                return await self.bot.db.fetchval(
                    f"""
                    SELECT {col} FROM {table}
                    WHERE guild_id = $1 AND channel_id = $2
                      AND message_id = $3 AND emoji = $4
                    """,
                    self.guild.id,
                    channel_id,
                    message_id,
                    self.emoji,
                )
            except Exception:
                continue
        return None

    async def save_star(self, *, stars: int, message, content: str, embed) -> None:
        """Create or update the archived starboard post."""
        board = self.channel
        if board is None:
            return
        existing = await self.get_star_message_id(message.id, message.channel.id)
        if existing:
            try:
                await board.get_partial_message(int(existing)).edit(
                    content=content, embed=embed
                )
                return
            except Exception:
                pass
        try:
            posted = await board.send(content=content, embed=embed)
        except Exception:
            return
        for table, col in (
            ("starboard_entry", "star_id"),
            ("starboard_entries", "starboard_message_id"),
        ):
            try:
                await self.bot.db.execute(
                    f"""
                    INSERT INTO {table}
                        (guild_id, channel_id, message_id, emoji, {col})
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    self.guild.id,
                    message.channel.id,
                    message.id,
                    self.emoji,
                    posted.id,
                )
            except Exception:
                try:
                    await self.bot.db.execute(
                        f"""
                        INSERT INTO {table}
                            (guild_id, channel_id, message_id, emoji, {col})
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        self.guild.id,
                        message.channel.id,
                        message.id,
                        self.emoji,
                        posted.id,
                    )
                except Exception:
                    continue

    async def delete_star(self, *, message_id: int, channel_id: int) -> None:
        board = self.channel
        star_id = await self.get_star_message_id(message_id, channel_id)
        if star_id and board is not None:
            try:
                await board.get_partial_message(int(star_id)).delete()
            except Exception:
                pass
        for table in ("starboard_entry", "starboard_entries"):
            try:
                await self.bot.db.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE guild_id = $1 AND channel_id = $2
                      AND message_id = $3 AND emoji = $4
                    """,
                    self.guild.id,
                    channel_id,
                    message_id,
                    self.emoji,
                )
            except Exception:
                continue



class Settings(Config):
    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Config:
        rows = await cls.fetch_all(bot, guild)
        if rows:
            return rows[0]
        return cls(bot, guild, {"guild_id": guild.id})

    @classmethod
    async def exists(cls, bot: Vain, guild: Guild) -> bool:
        return bool(
            await bot.db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM starboard WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, **kwargs: Any) -> Config:
        data = {**self.record, **kwargs, "guild_id": self.guild.id}
        if "emoji" not in data:
            data["emoji"] = "⭐"
        if "channel_id" not in data or not data["channel_id"]:
            return self
        cfg = await Config.upsert(
            self.bot,
            self.guild,
            channel_id=int(data["channel_id"]),
            emoji=str(data.get("emoji") or "⭐"),
            threshold=int(data.get("threshold") or 3),
            self_star=bool(data.get("self_star", True)),
        )
        self.record = cfg.record
        return self


__all__ = ["Config", "Settings", "Record"]
