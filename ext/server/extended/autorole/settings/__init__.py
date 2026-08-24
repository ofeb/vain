from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain

logger = getLogger("vain.autorole.settings")


class Settings:
    """All `auto_role` rows for one guild (role_id)."""

    bot: Vain
    guild: Guild
    rows: list[dict[str, Any]]

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.rows = list(rows or [])

    def __bool__(self) -> bool:
        return bool(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        rows = await bot.db.fetch(
            "SELECT * FROM auto_role WHERE guild_id = $1",
            guild.id,
        )
        return cls(bot, guild, [dict(r) for r in rows])

    @classmethod
    async def fetch_all(cls, bot: Vain, guild: Guild) -> list[dict[str, Any]]:
        settings = await cls.fetch(bot, guild)
        return settings.rows

    async def reload(self) -> Settings:
        fresh = await Settings.fetch(self.bot, self.guild)
        self.rows = fresh.rows
        return self

    async def add(self, **fields: Any) -> dict[str, Any]:
        """Insert an auto_role row if it does not already exist."""

        if not fields:
            raise ValueError("add() requires column fields")

        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(
            f"${i}" for i in range(1, len(cols) + 1)
        )
        col_sql = ", ".join(cols)

        row = await self.bot.db.fetchrow(
            f"""
            INSERT INTO auto_role ({col_sql})
            VALUES ({placeholders})
            ON CONFLICT (guild_id, role_id) DO NOTHING
            RETURNING *
            """,
            *values,
        )

        if row:
            data = dict(row)

            self.rows = [
                existing
                for existing in self.rows
                if not (
                    existing.get("guild_id") == self.guild.id
                    and existing.get("role_id") == fields.get("role_id")
                )
            ]
            self.rows.append(data)

            return data

        existing = next(
            (
                existing
                for existing in self.rows
                if existing.get("guild_id") == self.guild.id
                and existing.get("role_id") == fields.get("role_id")
            ),
            None,
        )

        if existing:
            return existing

        fresh = await self.bot.db.fetchrow(
            """
            SELECT *
            FROM auto_role
            WHERE guild_id = $1 AND role_id = $2
            """,
            self.guild.id,
            fields["role_id"],
        )

        if not fresh:
            raise RuntimeError("auto_role row exists but could not be fetched")

        data = dict(fresh)
        self.rows.append(data)
        return data

    async def remove_where(self, **match: Any) -> int:
        """Delete rows matching column equality filters (and this guild)."""
        if not match:
            raise ValueError("remove_where requires filters")
        clauses = ["guild_id = $1"]
        values: list[Any] = [self.guild.id]
        for i, (k, v) in enumerate(match.items(), start=2):
            clauses.append("%s = $%d" % (k, i))
            values.append(v)
        where = " AND ".join(clauses)
        result = await self.bot.db.execute(
            "DELETE FROM auto_role WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM auto_role WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []
        logger.debug("clear auto_role guild=%s", self.guild.id)

    async def upsert(self, **kwargs: Any) -> Settings:
        """Reload rows (multi-row writes use add / remove_where)."""
        return await self.reload()

    async def insert(self, **kwargs: Any) -> Settings:
        if kwargs:
            await self.add(**kwargs)
        return self


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def fetch_all(bot: Vain, guild: Guild) -> list[dict[str, Any]]:
    return await Settings.fetch_all(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.insert(**kwargs)


class ButtonRoleSettings:
    """All `button_roles` rows for one guild."""

    bot: Vain
    guild: Guild
    rows: list[dict[str, Any]]

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.rows = list(rows or [])

    def __bool__(self) -> bool:
        return bool(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> ButtonRoleSettings:
        rows = await bot.db.fetch(
            "SELECT * FROM button_roles WHERE guild_id = $1 ORDER BY index ASC",
            guild.id,
        )
        return cls(bot, guild, [dict(r) for r in rows])

    async def reload(self) -> ButtonRoleSettings:
        fresh = await ButtonRoleSettings.fetch(self.bot, self.guild)
        self.rows = fresh.rows
        return self

    async def add(self, **fields: Any) -> dict[str, Any]:
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO button_roles (%s) VALUES (%s) RETURNING *" % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        return data

    async def remove_where(self, **match: Any) -> int:
        if not match:
            raise ValueError("remove_where requires filters")
        clauses = ["guild_id = $1"]
        values: list[Any] = [self.guild.id]
        for i, (k, v) in enumerate(match.items(), start=2):
            clauses.append("%s = $%d" % (k, i))
            values.append(v)
        where = " AND ".join(clauses)
        result = await self.bot.db.execute(
            "DELETE FROM button_roles WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM button_roles WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []


class ReactionRoleSettings:
    """All `reaction_role` rows for one guild."""

    bot: Vain
    guild: Guild
    rows: list[dict[str, Any]]

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.rows = list(rows or [])

    def __bool__(self) -> bool:
        return bool(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> ReactionRoleSettings:
        rows = await bot.db.fetch(
            "SELECT * FROM reaction_role WHERE guild_id = $1",
            guild.id,
        )
        return cls(bot, guild, [dict(r) for r in rows])

    async def reload(self) -> ReactionRoleSettings:
        fresh = await ReactionRoleSettings.fetch(self.bot, self.guild)
        self.rows = fresh.rows
        return self

    async def add(self, **fields: Any) -> dict[str, Any]:
        if not fields:
            raise ValueError("add() requires column fields")
        cols = ["guild_id", *fields.keys()]
        values: list[Any] = [self.guild.id, *fields.values()]
        placeholders = ", ".join(f"$%d" % i for i in range(1, len(cols) + 1))
        col_sql = ", ".join(cols)
        row = await self.bot.db.fetchrow(
            f"INSERT INTO reaction_role (%s) VALUES (%s) ON CONFLICT(guild_id, channel_id, message_id, role_id) DO UPDATE SET emoji = excluded.emoji RETURNING *"
            % (col_sql, placeholders),
            *values,
        )
        data = dict(row) if row else {"guild_id": self.guild.id, **fields}
        self.rows.append(data)
        return data

    async def remove_where(self, **match: Any) -> int:
        if not match:
            raise ValueError("remove_where requires filters")
        clauses = ["guild_id = $1"]
        values: list[Any] = [self.guild.id]
        for i, (k, v) in enumerate(match.items(), start=2):
            clauses.append("%s = $%d" % (k, i))
            values.append(v)
        where = " AND ".join(clauses)
        result = await self.bot.db.execute(
            "DELETE FROM reaction_role WHERE %s" % where,
            *values,
        )
        await self.reload()
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def clear(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM reaction_role WHERE guild_id = $1",
            self.guild.id,
        )
        self.rows = []


__all__ = ["Settings", "ButtonRoleSettings", "ReactionRoleSettings", "fetch", "fetch_all", "upsert", "insert"]
