from __future__ import annotations

import secrets
from logging import getLogger
from typing import Any, TypedDict

from core.vain import Vain

logger = getLogger("vain.owner.settings")


class Record(TypedDict, total=False):
    bot_id: int


class Settings:
    """Row in `devlog_config` for one bot_id."""

    bot: Vain
    key: int
    record: dict[str, Any]

    def __init__(self, bot: Vain, key: int, record: dict[str, Any] | None = None) -> None:
        self.bot = bot
        self.key = int(key)
        self.record = dict(record or {'bot_id': self.key})

    def __bool__(self) -> bool:
        return self.record.get('bot_id') is not None and len(self.record) > 1

    def get(self, field: str, default: Any = None) -> Any:
        return self.record.get(field, default)

    @classmethod
    async def fetch(cls, bot: Vain, key: int) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM devlog_config WHERE bot_id = $1",
            int(key),
        )
        return cls(bot, key, dict(row) if row else None)

    async def upsert(self, **kwargs: Any) -> Settings:
        self.record.update(kwargs)
        self.record['bot_id'] = self.key
        cols = ['bot_id'] + [k for k in kwargs if k != 'bot_id']
        values = [self.record.get(c) for c in cols]
        placeholders = ", ".join("$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        updates = ", ".join(
            "%s = EXCLUDED.%s" % (c, c) for c in cols if c != 'bot_id'
        )
        if updates:
            query = (
                "INSERT INTO devlog_config (%s) VALUES (%s) "
                "ON CONFLICT (bot_id) DO UPDATE SET %s RETURNING *"
            ) % (col_sql, placeholders, updates)
        else:
            query = (
                "INSERT INTO devlog_config (%s) VALUES (%s) "
                "ON CONFLICT (bot_id) DO NOTHING RETURNING *"
            ) % (col_sql, placeholders)
        row = await self.bot.db.fetchrow(query, *values)
        if row:
            self.record = dict(row)
        logger.debug("upsert devlog_config bot_id=%s", self.key)
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM devlog_config WHERE bot_id = $1",
            self.key,
        )
        self.record = {'bot_id': self.key}

    

    async def get_devlog_channel_id(self) -> int | None:
        settings = await self.fetch(self.bot, self.key)
        return settings.get('channel_id')

    

    @staticmethod
    async def ensure_blacklist_history(db) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist_history (
                hash TEXT PRIMARY KEY,
                user_id BIGINT,
                guild_id BIGINT,
                action TEXT NOT NULL,
                reason TEXT,
                moderator_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist_history_notes (
                id SERIAL PRIMARY KEY,
                history_hash TEXT NOT NULL,
                content TEXT NOT NULL,
                moderator_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

    @staticmethod
    def gen_bl_hash() -> str:
        return secrets.token_hex(3)[:5]

    @staticmethod
    async def record_blacklist_history(
        db,
        *,
        action: str,
        user_id: int | None = None,
        guild_id: int | None = None,
        reason: str | None = None,
        moderator_id: int | None = None,
    ) -> str:
        await Settings.ensure_blacklist_history(db)
        for _ in range(12):
            h = Settings.gen_bl_hash()
            try:
                await db.execute(
                    """
                    INSERT INTO blacklist_history
                        (hash, user_id, guild_id, action, reason, moderator_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    h, user_id, guild_id, action, reason, moderator_id,
                )
                return h
            except Exception:
                continue
        h = secrets.token_hex(4)
        await db.execute(
            """
            INSERT INTO blacklist_history
                (hash, user_id, guild_id, action, reason, moderator_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            h, user_id, guild_id, action, reason, moderator_id,
        )
        return h

    async def fetch_history_for_user(
        self, user_id: int, actions: list[str]
    ) -> list[dict]:
        rows = await self.bot.db.fetch(
            """
            SELECT hash, action, reason, moderator_id, created_at
            FROM blacklist_history
            WHERE user_id = $1 AND action = ANY($2::text[])
            ORDER BY created_at DESC
            """,
            user_id,
            actions,
        )
        return [dict(r) for r in rows]

    async def fetch_notes_for_hashes(self, hashes: list[str]) -> list[dict]:
        if not hashes:
            return []
        rows = await self.bot.db.fetch(
            """
            SELECT id, history_hash, content, moderator_id, created_at
            FROM blacklist_history_notes
            WHERE history_hash = ANY($1::text[])
            ORDER BY created_at ASC
            """,
            hashes,
        )
        return [dict(r) for r in rows]

    async def fetch_history_by_hash(self, hash: str) -> dict | None:
        row = await self.bot.db.fetchrow(
            "SELECT hash, user_id FROM blacklist_history WHERE hash = $1",
            hash,
        )
        return dict(row) if row else None

    async def fetch_latest_history_for_user(self, user_id: int) -> dict | None:
        row = await self.bot.db.fetchrow(
            """
            SELECT hash FROM blacklist_history
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row else None

    

    async def delete_notes_for_hash(self, history_hash: str) -> None:
        await self.bot.db.execute(
            "DELETE FROM blacklist_history_notes WHERE history_hash = $1",
            history_hash,
        )

    async def add_note(
        self, history_hash: str, content: str, moderator_id: int
    ) -> int:
        note_id = await self.bot.db.fetchval(
            """
            INSERT INTO blacklist_history_notes (history_hash, content, moderator_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            history_hash,
            content[:1000],
            moderator_id,
        )
        return note_id

    async def fetch_note_by_id(self, note_id: int) -> dict | None:
        row = await self.bot.db.fetchrow(
            "SELECT id, history_hash FROM blacklist_history_notes WHERE id = $1",
            note_id,
        )
        return dict(row) if row else None

    async def delete_note_by_id(self, note_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM blacklist_history_notes WHERE id = $1", note_id
        )

    async def update_note_by_id(self, note_id: int, content: str) -> None:
        await self.bot.db.execute(
            "UPDATE blacklist_history_notes SET content = $2 WHERE id = $1",
            note_id,
            content[:1000],
        )

    

    async def blacklist_guild(self, guild_id: int, reason: str | None) -> None:
        await self.bot.db.execute(
            "DELETE FROM blacklist WHERE guild_id = $1", guild_id
        )
        await self.bot.db.execute(
            "INSERT INTO blacklist (user_id, guild_id, reason) VALUES (NULL, $1, $2)",
            guild_id, reason,
        )

    async def blacklist_user(self, user_id: int, reason: str | None) -> None:
        await self.bot.db.execute(
            "DELETE FROM blacklist WHERE user_id = $1", user_id
        )
        await self.bot.db.execute(
            "INSERT INTO blacklist (user_id, guild_id, reason) VALUES ($1, NULL, $2)",
            user_id, reason,
        )

    async def fetch_blacklist(self) -> list[dict]:
        rows = await self.bot.db.fetch(
            "SELECT user_id, guild_id, reason, created_at FROM blacklist ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def remove_blacklist_guild(self, guild_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM blacklist WHERE guild_id = $1", guild_id
        )

    async def remove_blacklist_user(self, user_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM blacklist WHERE user_id = $1", user_id
        )


async def fetch(bot: Vain, key: int) -> Settings:
    return await Settings.fetch(bot, key)


async def upsert(bot: Vain, key: int, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, key)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, key: int, **kwargs: Any) -> Settings:
    return await upsert(bot, key, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
