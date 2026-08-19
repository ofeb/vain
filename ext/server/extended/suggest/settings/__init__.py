from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.server.extended.suggest.settings')

DEFAULT_UPVOTE = "\u2705"
DEFAULT_DOWNVOTE = "\u274c"


class Record(TypedDict, total=False):
    """DB row for `suggest_settings`."""

    guild_id: int
    enabled: bool
    channel_id: Any | None
    review_enabled: bool
    review_channel_id: Any | None
    threads_enabled: bool
    upvote_emoji: str
    downvote_emoji: str


class Settings:
    """Guild settings for `suggest_settings`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get('enabled'))

    @property
    def enabled(self) -> bool:
        return bool(self.record.get('enabled', False))

    @property
    def channel_id(self) -> Any | None:
        return self.record.get('channel_id')

    @property
    def review_enabled(self) -> bool:
        return bool(self.record.get('review_enabled', False))

    @property
    def review_channel_id(self) -> Any | None:
        return self.record.get('review_channel_id')

    @property
    def threads_enabled(self) -> bool:
        return bool(self.record.get('threads_enabled', False))

    @property
    def upvote_emoji(self) -> str:
        return self.record.get('upvote_emoji', '✅')

    @property
    def downvote_emoji(self) -> str:
        return self.record.get('downvote_emoji', '❌')

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('channel_id')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'enabled': False,
            'channel_id': None,
            'review_enabled': False,
            'review_channel_id': None,
            'threads_enabled': False,
            'upvote_emoji': '✅',
            'downvote_emoji': '❌',
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM suggest_settings WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM suggest_settings WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'enabled': kwargs.get('enabled', self.enabled),
            'channel_id': kwargs.get('channel_id', self.channel_id),
            'review_enabled': kwargs.get('review_enabled', self.review_enabled),
            'review_channel_id': kwargs.get('review_channel_id', self.review_channel_id),
            'threads_enabled': kwargs.get('threads_enabled', self.threads_enabled),
            'upvote_emoji': kwargs.get('upvote_emoji', self.upvote_emoji),
            'downvote_emoji': kwargs.get('downvote_emoji', self.downvote_emoji),
        }
        query = """
        INSERT INTO suggest_settings (guild_id, enabled, channel_id, review_enabled, review_channel_id, threads_enabled, upvote_emoji, downvote_emoji)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (guild_id) DO UPDATE SET
            enabled = EXCLUDED.enabled,
            channel_id = EXCLUDED.channel_id,
            review_enabled = EXCLUDED.review_enabled,
            review_channel_id = EXCLUDED.review_channel_id,
            threads_enabled = EXCLUDED.threads_enabled,
            upvote_emoji = EXCLUDED.upvote_emoji,
            downvote_emoji = EXCLUDED.downvote_emoji
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['enabled'],
            values['channel_id'],
            values['review_enabled'],
            values['review_channel_id'],
            values['threads_enabled'],
            values['upvote_emoji'],
            values['downvote_emoji'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert suggest_settings guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM suggest_settings WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    @staticmethod
    async def ensure_schema(bot: Vain) -> None:
        await bot.db.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS suggest_settings (
                guild_id BIGINT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                channel_id BIGINT,
                review_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                review_channel_id BIGINT,
                threads_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                upvote_emoji TEXT NOT NULL DEFAULT chr(9989),
                downvote_emoji TEXT NOT NULL DEFAULT chr(10060),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await bot.db.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS suggest_counters (
                guild_id BIGINT PRIMARY KEY,
                next_id BIGINT NOT NULL DEFAULT 1
            )
            """
        )
        await bot.db.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS suggestions (
                guild_id BIGINT NOT NULL,
                suggestion_id BIGINT NOT NULL,
                author_id BIGINT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                channel_id BIGINT,
                message_id BIGINT,
                review_channel_id BIGINT,
                review_message_id BIGINT,
                thread_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, suggestion_id)
            )
            """
        )
        await bot.db.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS suggest_ignored (
                guild_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                target_type TEXT NOT NULL,
                added_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, target_id, target_type)
            )
            """
        )
        await bot.db.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS suggest_votes (
                guild_id BIGINT NOT NULL,
                suggestion_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                vote TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, suggestion_id, user_id)
            )
            """
        )
        await bot.db.pool.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_message
            ON suggestions (guild_id, message_id)
            WHERE message_id IS NOT NULL
            """
        )
        await bot.db.pool.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_review_message
            ON suggestions (guild_id, review_message_id)
            WHERE review_message_id IS NOT NULL
            """
        )

    @classmethod
    async def fetch_settings(cls, bot: Vain, guild_id: int) -> dict[str, Any]:
        row = await bot.db.fetchrow(
            """
            SELECT enabled, channel_id, review_enabled, review_channel_id,
                   threads_enabled, upvote_emoji, downvote_emoji
            FROM suggest_settings
            WHERE guild_id = $1
            """,
            guild_id,
        )
        if not row:
            return {
                "enabled": False,
                "channel_id": None,
                "review_enabled": False,
                "review_channel_id": None,
                "threads_enabled": False,
                "upvote_emoji": DEFAULT_UPVOTE,
                "downvote_emoji": DEFAULT_DOWNVOTE,
            }
        return {
            "enabled": bool(row["enabled"]),
            "channel_id": int(row["channel_id"]) if row["channel_id"] else None,
            "review_enabled": bool(row["review_enabled"]),
            "review_channel_id": int(row["review_channel_id"]) if row["review_channel_id"] else None,
            "threads_enabled": bool(row["threads_enabled"]),
            "upvote_emoji": row["upvote_emoji"] or DEFAULT_UPVOTE,
            "downvote_emoji": row["downvote_emoji"] or DEFAULT_DOWNVOTE,
        }

    @classmethod
    async def set_settings(cls, bot: Vain, guild_id: int, **fields) -> None:
        if not fields:
            return
        columns = list(fields.keys())
        values = list(fields.values())
        inserts = ", ".join(["guild_id", *columns, "updated_at"])
        params = ", ".join(f"${index}" for index in range(1, len(values) + 2))
        updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
        await bot.db.execute(
            f"""
            INSERT INTO suggest_settings ({inserts})
            VALUES ({params}, CURRENT_TIMESTAMP)
            ON CONFLICT (guild_id) DO UPDATE SET
                {updates},
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            *values,
        )

    @staticmethod
    async def next_suggestion_id(bot: Vain, guild_id: int) -> int:
        async with bot.db.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO suggest_counters (guild_id, next_id)
                    VALUES ($1, 2)
                    ON CONFLICT (guild_id) DO UPDATE SET
                        next_id = suggest_counters.next_id + 1
                    RETURNING next_id - 1 AS suggestion_id
                    """,
                    guild_id,
                )
        return int(row["suggestion_id"])

    @staticmethod
    async def insert_suggestion(
        bot: Vain,
        guild_id: int,
        suggestion_id: int,
        author_id: int,
        content: str,
        status: str,
    ) -> None:
        await bot.db.execute(
            """
            INSERT INTO suggestions (guild_id, suggestion_id, author_id, content, status)
            VALUES ($1, $2, $3, $4, $5)
            """,
            guild_id,
            suggestion_id,
            author_id,
            content,
            status,
        )

    @staticmethod
    async def get_suggestion(
        bot: Vain, guild_id: int, suggestion_id: int
    ):
        return await bot.db.fetchrow(
            """
            SELECT *
            FROM suggestions
            WHERE guild_id = $1 AND suggestion_id = $2
            """,
            guild_id,
            suggestion_id,
        )

    @staticmethod
    async def get_suggestion_by_message(
        bot: Vain, guild_id: int, message_id: int
    ):
        return await bot.db.fetchrow(
            """
            SELECT *
            FROM suggestions
            WHERE guild_id = $1
              AND (message_id = $2 OR review_message_id = $2)
            """,
            guild_id,
            message_id,
        )

    @staticmethod
    async def set_suggestion_fields(
        bot: Vain, guild_id: int, suggestion_id: int, **fields
    ) -> None:
        if not fields:
            return
        keys = list(fields.keys())
        values = list(fields.values())
        assignments = ", ".join(
            f"{key} = ${index + 3}" for index, key in enumerate(keys)
        )
        await bot.db.execute(
            f"""
            UPDATE suggestions
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = $1 AND suggestion_id = $2
            """,
            guild_id,
            suggestion_id,
            *values,
        )

    @staticmethod
    async def set_vote(
        bot: Vain, guild_id: int, suggestion_id: int, user_id: int, vote: str
    ) -> None:
        await bot.db.execute(
            """
            INSERT INTO suggest_votes (guild_id, suggestion_id, user_id, vote)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, suggestion_id, user_id) DO UPDATE SET
                vote = EXCLUDED.vote,
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            suggestion_id,
            user_id,
            vote,
        )

    @staticmethod
    async def remove_vote(
        bot: Vain, guild_id: int, suggestion_id: int, user_id: int, vote: str
    ) -> None:
        await bot.db.execute(
            """
            DELETE FROM suggest_votes
            WHERE guild_id = $1 AND suggestion_id = $2 AND user_id = $3 AND vote = $4
            """,
            guild_id,
            suggestion_id,
            user_id,
            vote,
        )

    @staticmethod
    async def toggle_ignored_entry(
        bot: Vain, guild_id: int, target_id: int, target_type: str, added_by: int
    ) -> bool:
        inserted = await bot.db.fetchrow(
            """
            INSERT INTO suggest_ignored (guild_id, target_id, target_type, added_by)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            RETURNING guild_id
            """,
            guild_id,
            target_id,
            target_type,
            added_by,
        )
        if inserted:
            return True
        await bot.db.execute(
            """
            DELETE FROM suggest_ignored
            WHERE guild_id = $1 AND target_id = $2 AND target_type = $3
            """,
            guild_id,
            target_id,
            target_type,
        )
        return False

    @staticmethod
    async def list_ignored_entries(bot: Vain, guild_id: int):
        return await bot.db.fetch(
            """
            SELECT target_id, target_type
            FROM suggest_ignored
            WHERE guild_id = $1
            ORDER BY target_type, target_id
            """,
            guild_id,
        )

    @staticmethod
    async def is_ignored(bot: Vain, guild_id: int, member_id: int, role_ids: list[int]) -> bool:
        return bool(
            await bot.db.fetchval(
                """
                SELECT 1
                FROM suggest_ignored
                WHERE guild_id = $1
                  AND (
                    (target_type = 'member' AND target_id = $2)
                    OR
                    (target_type = 'role' AND target_id = ANY($3::BIGINT[]))
                  )
                LIMIT 1
                """,
                guild_id,
                member_id,
                role_ids,
            )
        )


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
