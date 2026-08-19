from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.server.extended.filter.settings")

MODULES = ("caps", "spam", "links", "invites", "spoilers", "music", "words")


class Settings:
    """Aggregated automod filter configuration for one guild."""

    bot: Vain
    guild: Guild
    modules: dict[str, dict[str, Any]]

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        modules: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.modules = dict(modules or {})

    def __bool__(self) -> bool:
        return any(self.modules.values())

    def get(self, module: str) -> dict[str, Any] | None:
        return self.modules.get(module)

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        modules: dict[str, dict[str, Any]] = {}
        for name in MODULES:
            try:
                row = await bot.db.fetchrow(
                    f"SELECT * FROM moderation.{name} WHERE guild_id = $1",
                    guild.id,
                )
            except Exception:
                row = None
            if row:
                modules[name] = dict(row)
        return cls(bot, guild, modules)

    async def upsert_module(self, module: str, **fields: Any) -> dict[str, Any]:
        if module not in MODULES:
            raise ValueError(f"unknown filter module {module}")
        current = dict(self.modules.get(module) or {})
        current.update(fields)
        current["guild_id"] = self.guild.id
        cols = list(current.keys())
        values = [current[c] for c in cols]
        placeholders = ", ".join("$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        updates = ", ".join(
            "%s = EXCLUDED.%s" % (c, c) for c in cols if c != "guild_id"
        )
        query = (
            "INSERT INTO moderation.%s (%s) VALUES (%s) "
            "ON CONFLICT (guild_id) DO UPDATE SET %s RETURNING *"
        ) % (module, col_sql, placeholders, updates)
        row = await self.bot.db.fetchrow(query, *values)
        data = dict(row) if row else current
        self.modules[module] = data
        logger.debug("upsert filter.%s guild=%s", module, self.guild.id)
        return data

    async def delete_module(self, module: str) -> None:
        await self.bot.db.execute(
            f"DELETE FROM moderation.{module} WHERE guild_id = $1",
            self.guild.id,
        )
        self.modules.pop(module, None)

    async def upsert(self, module: str | None = None, **kwargs: Any) -> Settings:
        if module:
            await self.upsert_module(module, **kwargs)
        return self

    async def insert(self, module: str | None = None, **kwargs: Any) -> Settings:
        return await self.upsert(module, **kwargs)

    async def ensure_words_table(self) -> None:
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS filter_words (
                guild_id BIGINT NOT NULL,
                word TEXT NOT NULL,
                PRIMARY KEY (guild_id, word)
            )
            """
        )

    async def add_filter_words(self, guild_id: int, words: list[str]) -> None:
        for w in words:
            await self.bot.db.execute(
                """
                INSERT INTO filter_words (guild_id, word)
                VALUES ($1, $2)
                ON CONFLICT (guild_id, word) DO NOTHING
                """,
                guild_id,
                w,
            )

    async def fetch_filter_words(self, guild_id: int) -> list[str]:
        rows = await self.bot.db.fetch(
            "SELECT word FROM filter_words WHERE guild_id = $1 ORDER BY word",
            guild_id,
        )
        return [r["word"] for r in rows]

    async def remove_filter_words(self, guild_id: int, words: list[str]) -> list[str]:
        remaining = set()
        for w in words:
            await self.bot.db.execute(
                "DELETE FROM filter_words WHERE guild_id = $1 AND word = $2",
                guild_id,
                w,
            )
        rows = await self.bot.db.fetch(
            "SELECT word FROM filter_words WHERE guild_id = $1 ORDER BY word",
            guild_id,
        )
        remaining = {r["word"] for r in rows}
        return [w for w in words if w not in remaining]

    async def clear_filter_words(self, guild_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM filter_words WHERE guild_id = $1",
            guild_id,
        )

    async def get_exempt_roles(self, module: str, guild_id: int) -> list[int]:
        row = await self.bot.db.fetchrow(
            f"SELECT exempt_roles FROM moderation.{module} WHERE guild_id = $1",
            guild_id,
        )
        if not row:
            return []
        return list(row.exempt_roles or [])

    async def set_exempt_roles(
        self, module: str, guild_id: int, roles: list[int]
    ) -> None:
        await self.bot.db.execute(
            f"UPDATE moderation.{module} SET exempt_roles = $1 WHERE guild_id = $2",
            roles,
            guild_id,
        )

    async def fetch_regex_patterns(self, guild_id: int) -> list[str]:
        rows = await self.bot.db.fetch(
            "SELECT regex FROM moderation.regex WHERE guild_id = $1",
            guild_id,
        )
        return [r.regex for r in rows]

    async def fetch_regex_row(
        self, guild_id: int, pattern: str
    ) -> dict | None:
        row = await self.bot.db.fetchrow(
            "SELECT id FROM moderation.regex WHERE guild_id = $1 AND regex = $2",
            guild_id,
            pattern,
        )
        return dict(row) if row else None

    async def delete_regex(self, guild_id: int, pattern: str) -> None:
        await self.bot.db.execute(
            "DELETE FROM moderation.regex WHERE guild_id = $1 AND regex = $2",
            guild_id,
            pattern,
        )

    async def upsert_regex(
        self, guild_id: int, pattern: str, action: str
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO moderation.regex (guild_id, regex, action)
               VALUES($1, $2, $3)
               ON CONFLICT(guild_id, regex) DO UPDATE SET action = $3""",
            guild_id,
            pattern,
            action,
        )


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, module: str, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    await settings.upsert_module(module, **kwargs)
    return settings


async def insert(bot: Vain, guild: Guild, module: str, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, module, **kwargs)


__all__ = ["Settings", "MODULES", "fetch", "upsert", "insert"]
