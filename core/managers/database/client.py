"""postgres database connection pool.
wraps asyncpg with basic caching built in.
use fetch fetchrow fetchval or execute"""

from __future__ import annotations
from datetime import datetime
import asyncio, contextlib, glob, json, re
from logging import getLogger
from types import TracebackType
from typing import Any, Iterable, Optional, Protocol, Sequence, Union
from urllib.parse import unquote, urlsplit
import ujson
from asyncpg import Connection, Pool, Record as BaseRecord, create_pool
from asyncpg.exceptions import InvalidCatalogNameError
from discord.ext.commands import Context, check
from ..values import database

log = getLogger(__name__)


def query_limit(table: str, limit: int = 5):
    """check row count before insert"""
    async def predicate(ctx: Context):
        count = await ctx.bot.db.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE guild_id = $1", ctx.guild.id
        )
        if count == limit:
            await ctx.fail(f"cant make more than **{limit}** {table}s")
            return False
        return True
    return check(predicate)


class Row(BaseRecord):
    """asyncpg record with attr access"""
    def __getattr__(self, name: Union[str, Any]) -> Any:
        return self[name]

    def __dict__(self) -> dict:
        return dict(self)


class ConnProto(Protocol):
    """connection context manager type"""
    async def __aenter__(self) -> Connection: ...
    async def __aexit__(self, et, ev, tb) -> None: ...


class Database:
    """postgres pool wrapper with cache"""

    def __init__(self):
        self.uri: str = database.dsn
        self.pool: Optional[Pool] = None
        self.cache: dict = {}

    def _encode(self, *data: Any):
        return ujson.dumps(data[1])

    def _decode(self, *data: Any):
        return ujson.loads(data[1])

    async def _init_conn(self, conn: Connection) -> None:
        for name in ("json", "jsonb"):
            await conn.set_type_codec(
                name,
                encoder=self._encode,
                decoder=self._decode,
                schema="pg_catalog",
            )

    async def _make_pool(self) -> Pool:
        pool = await create_pool(dsn=self.uri, init=self._init_conn, record_class=Row)
        log.info(f"db pool ready {pool.__hash__()}")
        return pool

    def _create_db(self, name: str, user: str, pw: str, host: str, port: int):
        """create db if not exists"""
        import psycopg2
        conn = psycopg2.connect(dbname="postgres", user=user, password=pw, host=host, port=port)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE {name};")
            with open("var/migrations.sql", "r") as f:
                cur.execute(f.read())
        conn.close()

    @staticmethod
    def _dsn_parts(uri: str) -> tuple[str, str, str, int, str]:
        parsed = urlsplit(uri)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError(f"unsupported database scheme: {parsed.scheme or 'missing'}")
        if not parsed.hostname:
            raise ValueError("database host is missing")
        return (
            unquote(parsed.username or ""),
            unquote(parsed.password or ""),
            parsed.hostname,
            parsed.port or 5432,
            parsed.path.lstrip("/") or "postgres",
        )

    async def connect(self) -> Pool:
        """open pool, create db if missing"""
        user, pw, host, port, name = self._dsn_parts(self.uri)
        try:
            self.pool = await self._make_pool()
        except InvalidCatalogNameError:
            await asyncio.to_thread(self._create_db, name, user, pw, host, port)
            self.pool = await self._make_pool()
        try:
            await self.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        except Exception as e:
            log.warning(f"timescaledb not available: {e}")
        return self.pool

    async def close(self) -> None:
        """close pool connection"""
        if self.pool:
            await self.pool.close()
            log.info("db pool closed")

    async def _bust(self, key: str) -> None:
        """remove cache entry after delay"""
        await asyncio.sleep(60)
        self.cache.pop(key, None)

    async def _store(self, data: Any, op: str, sql: str, args) -> None:
        if "economy" not in sql.lower():
            self.cache[f"{op} {sql} {args}"] = data

    async def _purge_table(self, table: str) -> None:
        keys = [k for k in self.cache if table.lower() in k.lower()]
        for k in keys:
            self.cache.pop(k, None)

    @staticmethod
    def _write_table(sql: str) -> Optional[str]:
        """extract the target table from a simple write statement"""
        normalized = " ".join(sql.lower().split())
        for pattern in (
            r"^insert into ([a-z0-9_.]+)",
            r"^update ([a-z0-9_.]+)",
            r"^delete from ([a-z0-9_.]+)",
        ):
            if match := re.match(pattern, normalized):
                return match.group(1)
        return None

    async def fetch(self, sql: str, *args, **kw) -> list:
        """fetch all rows"""
        key = f"fetch {sql} {args}"
        if kw.get("cached", True) and (hit := self.cache.get(key)):
            return hit
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await conn.fetch(sql, *args)
                await self._store(data, "fetch", sql, args)
                return data

    async def fetchiter(self, sql: str, *args):
        """yield rows one by one"""
        for row in await self.fetch(sql, *args):
            yield row

    async def fetchrow(self, sql: str, *args, **kw) -> Optional[Row]:
        """fetch single row"""
        key = f"fetchrow {sql} {args}"
        if kw.get("cached", True) and (hit := self.cache.get(key)):
            return hit
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await conn.fetchrow(sql, *args)
                await self._store(data, "fetchrow", sql, args)
                return data

    async def fetchval(self, sql: str, *args, **kw) -> Any:
        """fetch single value"""
        key = f"fetchval {sql} {args}"
        if kw.get("cached", True) and (hit := self.cache.get(key)):
            return hit
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await conn.fetchval(sql, *args)
                await self._store(data, "fetchval", sql, args)
                return data

    async def execute(self, sql: str, *args, **kw) -> Any:
        """run a write query"""
        args = [json.dumps(a) if isinstance(a, dict) else a for a in args]
        if table := self._write_table(sql):
            await self._purge_table(table)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.fetchval(sql, *args)

    async def executemany(self, sql: str, args: Iterable[Sequence]) -> Any:
        """run query with multiple arg sets"""
        self.cache.pop(f"{sql} {args}", None)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.executemany(sql, args)

    async def toggle_antinuke_admin(self, guild_id: int, user_id: int) -> bool:
        """toggle a stored antinuke admin"""
        admins = await self.fetchval(
            """
            INSERT INTO antinuke (guild_id, admins)
            VALUES ($1, ARRAY[$2]::BIGINT[])
            ON CONFLICT (guild_id) DO UPDATE
            SET admins = CASE
                WHEN $2 = ANY(antinuke.admins) THEN array_remove(antinuke.admins, $2)
                ELSE antinuke.admins || ARRAY[$2]::BIGINT[]
            END
            RETURNING admins
            """,
            guild_id,
            user_id,
            cached=False,
        ) or []
        return int(user_id) in set(int(value) for value in admins)

    async def fetch_antinuke_admins(self, guild_id: int) -> list[int]:
        """list stored antinuke admin ids for a guild"""
        values = await self.fetchval(
            "SELECT admins FROM antinuke WHERE guild_id = $1",
            guild_id,
        ) or []
        return [int(value) for value in values]

    async def is_antinuke_admin(self, guild_id: int, user_id: int) -> bool:
        """check whether a user is an antinuke admin"""
        return bool(
            await self.fetchval(
                """
                SELECT 1
                FROM antinuke
                WHERE guild_id = $1 AND $2 = ANY(admins)
                """,
                guild_id,
                user_id,
            )
        )

    async def toggle_antinuke_whitelist(
        self,
        guild_id: int,
        user_id: int,
        is_bot: bool | None = None,
    ) -> bool:
        """toggle a user or bot in the antinuke whitelist"""
        whitelist = await self.fetchval(
            """
            INSERT INTO antinuke (guild_id, whitelist)
            VALUES ($1, ARRAY[$2]::BIGINT[])
            ON CONFLICT (guild_id) DO UPDATE
            SET whitelist = CASE
                WHEN $2 = ANY(antinuke.whitelist) THEN array_remove(antinuke.whitelist, $2)
                ELSE antinuke.whitelist || ARRAY[$2]::BIGINT[]
            END
            RETURNING whitelist
            """,
            guild_id,
            user_id,
            cached=False,
        ) or []
        return int(user_id) in set(int(value) for value in whitelist)

    async def add_antinuke_whitelist(
        self,
        guild_id: int,
        user_id: int,
        is_bot: bool | None = None,
    ) -> bool:
        """add a user or bot to the antinuke whitelist if absent"""
        existing = await self.is_antinuke_whitelisted(guild_id, user_id)
        if existing:
            return False
        await self.execute(
            """
            INSERT INTO antinuke (guild_id, whitelist)
            VALUES ($1, ARRAY[$2]::BIGINT[])
            ON CONFLICT (guild_id) DO UPDATE
            SET whitelist = antinuke.whitelist || ARRAY[$2]::BIGINT[]
            """,
            guild_id,
            user_id,
        )
        return True

    async def fetch_antinuke_whitelist(self, guild_id: int) -> list[int]:
        """list stored antinuke whitelist ids for a guild"""
        values = await self.fetchval(
            "SELECT whitelist FROM antinuke WHERE guild_id = $1",
            guild_id,
        ) or []
        return [int(value) for value in values]

    async def is_antinuke_whitelisted(self, guild_id: int, user_id: int) -> bool:
        """check whether a user or bot is antinuke-whitelisted"""
        return bool(
            await self.fetchval(
                """
                SELECT 1
                FROM antinuke
                WHERE guild_id = $1 AND $2 = ANY(whitelist)
                """,
                guild_id,
                user_id,
            )
        )

    async def get_antinuke_module(self, guild_id: int, module: str) -> Optional[Row]:
        """fetch one antinuke module payload as a json row"""
        if module not in {
            "botadd",
            "webhook",
            "emoji",
            "ban",
            "kick",
            "channel",
            "role",
            "vanity",
        }:
            raise ValueError(f"invalid antinuke module: {module}")
        return await self.fetchrow(
            f"SELECT {module} FROM antinuke WHERE guild_id = $1",
            guild_id,
        )

    async def set_antiraid_state(self, guild_id: int, active: bool) -> None:
        """persist the current raid-state toggle for a guild"""
        await self.execute(
            """
            INSERT INTO antiraid_config (guild_id, raid_active)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET
                raid_active = EXCLUDED.raid_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            active,
        )

    async def get_antiraid_state(self, guild_id: int) -> bool:
        """return whether the guild is currently marked as raiding"""
        value = await self.fetchval(
            "SELECT raid_active FROM antiraid_config WHERE guild_id = $1",
            guild_id,
        )
        return bool(value)

    async def set_antiraid_punish_until(
        self,
        guild_id: int,
        until: datetime | None,
    ) -> None:
        """persist the punishment window end timestamp for massjoin protection"""
        await self.execute(
            """
            INSERT INTO antiraid_config (guild_id, punish_until)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET
                punish_until = EXCLUDED.punish_until,
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            until,
        )

    async def get_antiraid_punish_until(self, guild_id: int) -> datetime | None:
        """return the punishment window end for a guild if one is active"""
        return await self.fetchval(
            "SELECT punish_until FROM antiraid_config WHERE guild_id = $1",
            guild_id,
        )

    async def upsert_antiraid_module(
        self,
        guild_id: int,
        module: str,
        *,
        enabled: bool,
        threshold: int | None = None,
        action: str | None = None,
        lock_channels: bool | None = None,
        punish_new: bool | None = None,
    ) -> None:
        """insert or update one antiraid module row"""
        await self.execute(
            """
            INSERT INTO antiraid_modules (
                guild_id,
                module,
                enabled,
                threshold,
                action,
                lock_channels,
                punish_new
            )
            VALUES (
                $1,
                $2,
                $3,
                COALESCE($4, 5),
                COALESCE($5, 'ban'),
                COALESCE($6, FALSE),
                COALESCE($7, FALSE)
            )
            ON CONFLICT (guild_id, module) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                threshold = COALESCE($4, antiraid_modules.threshold),
                action = COALESCE($5, antiraid_modules.action),
                lock_channels = COALESCE($6, antiraid_modules.lock_channels),
                punish_new = COALESCE($7, antiraid_modules.punish_new),
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            module,
            enabled,
            threshold,
            action,
            lock_channels,
            punish_new,
        )

    async def get_antiraid_module(self, guild_id: int, module: str) -> Optional[Row]:
        """fetch one antiraid module row"""
        return await self.fetchrow(
            """
            SELECT module, enabled, threshold, action, lock_channels, punish_new
            FROM antiraid_modules
            WHERE guild_id = $1 AND module = $2
            """,
            guild_id,
            module,
        )

    async def fetch_antiraid_modules(self, guild_id: int) -> list[Row]:
        """fetch all antiraid module rows for a guild"""
        return await self.fetch(
            """
            SELECT module, enabled, threshold, action, lock_channels, punish_new
            FROM antiraid_modules
            WHERE guild_id = $1
            ORDER BY module
            """,
            guild_id,
        )

    async def toggle_antiraid_whitelist(self, guild_id: int, user_id: int) -> bool:
        """toggle a one-time antiraid whitelist entry"""
        exists = await self.fetchrow(
            "SELECT 1 FROM antiraid_whitelist WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        if exists:
            await self.execute(
                "DELETE FROM antiraid_whitelist WHERE guild_id = $1 AND user_id = $2",
                guild_id,
                user_id,
            )
            return False

        await self.execute(
            "INSERT INTO antiraid_whitelist (guild_id, user_id) VALUES ($1, $2)",
            guild_id,
            user_id,
        )
        return True

    async def consume_antiraid_whitelist(self, guild_id: int, user_id: int) -> bool:
        """consume a one-time antiraid whitelist entry on join"""
        exists = await self.fetchrow(
            "SELECT 1 FROM antiraid_whitelist WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        if not exists:
            return False

        await self.execute(
            "DELETE FROM antiraid_whitelist WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return True

    async def is_antiraid_whitelisted(self, guild_id: int, user_id: int) -> bool:
        """check whether a guild/user one-time antiraid whitelist exists"""
        return bool(
            await self.fetchrow(
                "SELECT 1 FROM antiraid_whitelist WHERE guild_id = $1 AND user_id = $2",
                guild_id,
                user_id,
            )
        )

    async def fetch_antiraid_whitelist(self, guild_id: int) -> list[Row]:
        """fetch one-time antiraid whitelist rows for a guild"""
        return await self.fetch(
            """
            SELECT user_id, created_at
            FROM antiraid_whitelist
            WHERE guild_id = $1
            ORDER BY created_at
            """,
            guild_id,
        )

    async def add_antiraid_locked_channel(self, guild_id: int, channel_id: int) -> None:
        """remember a text channel locked during raid state"""
        await self.execute(
            """
            INSERT INTO antiraid_locked_channels (guild_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id, channel_id) DO NOTHING
            """,
            guild_id,
            channel_id,
        )

    async def fetch_antiraid_locked_channels(self, guild_id: int) -> list[int]:
        """return channel ids locked by antiraid for a guild"""
        rows = await self.fetch(
            "SELECT channel_id FROM antiraid_locked_channels WHERE guild_id = $1",
            guild_id,
        )
        return [row.channel_id for row in rows]

    async def clear_antiraid_locked_channels(self, guild_id: int) -> None:
        """clear remembered locked-channel state for a guild"""
        await self.execute(
            "DELETE FROM antiraid_locked_channels WHERE guild_id = $1",
            guild_id,
        )

    async def add_webhook(
        self,
        guild_id: int,
        identifier: str,
        name: str,
        channel_id: int,
        webhook_id: int,
        token: str,
        owner_id: int,
    ) -> None:
        """upsert one stored webhook definition"""
        await self.execute(
            """
            INSERT INTO webhooks (
                guild_id,
                identifier,
                name,
                channel_id,
                webhook_id,
                token,
                owner_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, identifier) DO UPDATE SET
                name = EXCLUDED.name,
                channel_id = EXCLUDED.channel_id,
                webhook_id = EXCLUDED.webhook_id,
                token = EXCLUDED.token,
                owner_id = EXCLUDED.owner_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            identifier,
            name,
            channel_id,
            webhook_id,
            token,
            owner_id,
        )

    async def fetch_webhook_by_identifier(
        self,
        guild_id: int,
        identifier: str,
    ) -> Optional[Row]:
        """fetch one webhook row by the public bleed identifier"""
        return await self.fetchrow(
            "SELECT * FROM webhooks WHERE guild_id = $1 AND identifier = $2",
            guild_id,
            identifier,
        )

    async def fetch_webhook_by_name(self, guild_id: int, name: str) -> Optional[Row]:
        """fetch one webhook row by its stored name"""
        return await self.fetchrow(
            "SELECT * FROM webhooks WHERE guild_id = $1 AND name = $2",
            guild_id,
            name,
        )

    async def fetch_webhook_by_id(
        self,
        guild_id: int,
        webhook_id: int,
    ) -> Optional[Row]:
        """fetch one webhook row by the real Discord webhook id"""
        return await self.fetchrow(
            "SELECT * FROM webhooks WHERE guild_id = $1 AND webhook_id = $2",
            guild_id,
            webhook_id,
        )

    async def list_webhooks(self, guild_id: int) -> list[Row]:
        """list stored webhooks for a guild"""
        return await self.fetch(
            """
            SELECT *
            FROM webhooks
            WHERE guild_id = $1
            ORDER BY created_at
            """,
            guild_id,
        )

    async def set_webhook_lock(self, guild_id: int, identifier: str, locked: bool) -> bool:
        """toggle lock state for one stored webhook"""
        with contextlib.suppress(Exception):
            if table := self._write_table("UPDATE webhooks SET locked = $3 WHERE guild_id = $1 AND identifier = $2"):
                await self._purge_table(table)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    """
                    UPDATE webhooks
                    SET locked = $3, updated_at = CURRENT_TIMESTAMP
                    WHERE guild_id = $1 AND identifier = $2
                    """,
                    guild_id,
                    identifier,
                    locked,
                )
        return not status.endswith("0")

    async def remove_webhook(self, guild_id: int, identifier: str) -> bool:
        """delete one stored webhook row"""
        with contextlib.suppress(Exception):
            if table := self._write_table("DELETE FROM webhooks WHERE guild_id = $1 AND identifier = $2"):
                await self._purge_table(table)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    "DELETE FROM webhooks WHERE guild_id = $1 AND identifier = $2",
                    guild_id,
                    identifier,
                )
        return not status.endswith("0")

    async def log_antinuke_action(self, guild_id: int, user_id: int, action: str) -> None:
        """store one antinuke action for threshold counting"""
        await self.execute(
            """
            INSERT INTO antinuke_actions (guild_id, user_id, action)
            VALUES ($1, $2, $3)
            """,
            guild_id,
            user_id,
            action,
        )

    async def get_antinuke_action_count(
        self,
        guild_id: int,
        user_id: int,
        action: str,
        window_seconds: int,
    ) -> int:
        """count recent antinuke actions for one user/module window"""
        row = await self.fetchrow(
            """
            SELECT COUNT(*) AS total
            FROM antinuke_actions
            WHERE guild_id = $1
              AND user_id = $2
              AND action = $3
              AND created_at >= (
                    CURRENT_TIMESTAMP - ($4::INT || ' seconds')::INTERVAL
              )
            """,
            guild_id,
            user_id,
            action,
            window_seconds,
            cached=False,
        )
        if not row:
            return 0
        return int(row.total or 0)

    async def get_server_settings(self, guild_id: int) -> Optional[Row]:
        """fetch one guild settings row"""
        return await self.fetchrow(
            "SELECT * FROM server_settings WHERE guild_id = $1",
            guild_id,
        )

    async def set_server_settings(self, guild_id: int, **fields) -> None:
        """upsert one guild settings row with the provided fields"""
        if not fields:
            return
        columns = list(fields.keys())
        values = list(fields.values())
        insert_columns = ", ".join(columns)
        insert_params = ", ".join(f"${index}" for index in range(2, len(values) + 2))
        updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
        await self.execute(
            (
                "INSERT INTO server_settings (guild_id, "
                + insert_columns
                + ", updated_at) VALUES ($1, "
                + insert_params
                + ", CURRENT_TIMESTAMP) "
                + "ON CONFLICT (guild_id) DO UPDATE SET "
                + updates
                + ", updated_at = CURRENT_TIMESTAMP"
            ),
            guild_id,
            *values,
        )

    async def reset_server_settings(self, guild_id: int) -> None:
        """delete the guild settings row"""
        await self.execute(
            "DELETE FROM server_settings WHERE guild_id = $1",
            guild_id,
        )

    async def toggle_staff_role(self, guild_id: int, role_id: int) -> bool:
        """toggle a configured staff role"""
        existing = await self.fetchrow(
            "SELECT 1 FROM staff_roles WHERE guild_id = $1 AND role_id = $2",
            guild_id,
            role_id,
        )
        if existing:
            await self.execute(
                "DELETE FROM staff_roles WHERE guild_id = $1 AND role_id = $2",
                guild_id,
                role_id,
            )
            return False

        await self.execute(
            """
            INSERT INTO staff_roles (guild_id, role_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id, role_id) DO NOTHING
            """,
            guild_id,
            role_id,
        )
        return True

    async def list_staff_roles(self, guild_id: int) -> list[int]:
        """list configured staff role ids for a guild"""
        rows = await self.fetch(
            """
            SELECT role_id
            FROM staff_roles
            WHERE guild_id = $1
            ORDER BY created_at
            """,
            guild_id,
        )
        return [int(row.role_id) for row in rows]

    async def set_modlog_channel(self, guild_id: int, channel_id: int) -> None:
        """upsert the guild modlog channel"""
        await self.execute(
            """
            INSERT INTO modlog_config (guild_id, channel_id, updated_at)
            VALUES ($1, $2, CURRENT_TIMESTAMP)
            ON CONFLICT (guild_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            channel_id,
        )

    async def get_modlog_channel(self, guild_id: int) -> int | None:
        """fetch the modlog channel id for a guild"""
        return await self.fetchval(
            "SELECT channel_id FROM modlog_config WHERE guild_id = $1",
            guild_id,
        )

    async def clear_modlog_channel(self, guild_id: int) -> None:
        """delete the modlog channel binding for a guild"""
        await self.execute(
            "DELETE FROM modlog_config WHERE guild_id = $1",
            guild_id,
        )

    async def create_case(
        self,
        guild_id: int,
        action: str,
        target_id: int | None,
        moderator_id: int | None,
        reason: str | None,
    ) -> int:
        """insert one modlog case and return the next case id"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT COALESCE(MAX(case_id), 0) + 1 AS next_id
                    FROM modlog_cases
                    WHERE guild_id = $1
                    """,
                    guild_id,
                )
                case_id = int(row["next_id"])
                await conn.execute(
                    """
                    INSERT INTO modlog_cases (
                        guild_id,
                        case_id,
                        action,
                        target_id,
                        moderator_id,
                        reason
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    guild_id,
                    case_id,
                    action,
                    target_id,
                    moderator_id,
                    reason,
                )
                return case_id

    async def reset_modlog_cases(self, guild_id: int) -> None:
        """delete all modlog cases for a guild"""
        await self.execute(
            "DELETE FROM modlog_cases WHERE guild_id = $1",
            guild_id,
        )

    async def add_tempban(
        self,
        guild_id: int,
        user_id: int,
        unban_at: datetime,
        moderator_id: int | None,
        reason: str | None,
        case_id: int | None,
    ) -> None:
        """insert or update one scheduled tempban"""
        await self.execute(
            """
            INSERT INTO tempbans (
                guild_id,
                user_id,
                unban_at,
                moderator_id,
                reason,
                case_id
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, user_id) DO UPDATE
            SET unban_at = EXCLUDED.unban_at,
                moderator_id = EXCLUDED.moderator_id,
                reason = EXCLUDED.reason,
                case_id = EXCLUDED.case_id
            """,
            guild_id,
            user_id,
            unban_at,
            moderator_id,
            reason,
            case_id,
        )

    async def remove_tempban(self, guild_id: int, user_id: int) -> None:
        """delete one scheduled tempban"""
        await self.execute(
            """
            DELETE FROM tempbans
            WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id,
            user_id,
        )

    async def fetch_due_tempbans(self) -> list[Row]:
        """list tempbans that should be removed now"""
        return await self.fetch(
            """
            SELECT *
            FROM tempbans
            WHERE unban_at <= CURRENT_TIMESTAMP
            ORDER BY unban_at
            """,
            cached=False,
        )

    async def toggle_autoresponder_exclusive(
        self,
        guild_id: int,
        trigger: str,
        target_type: str,
        target_id: int,
    ) -> bool:
        """toggle an exclusive channel or role target for one autoresponder"""
        existing = await self.fetchrow(
            """
            SELECT 1
            FROM autoresponder_exclusive
            WHERE guild_id = $1 AND trigger = $2 AND target_type = $3 AND target_id = $4
            """,
            guild_id,
            trigger,
            target_type,
            target_id,
        )
        if existing:
            await self.execute(
                """
                DELETE FROM autoresponder_exclusive
                WHERE guild_id = $1 AND trigger = $2 AND target_type = $3 AND target_id = $4
                """,
                guild_id,
                trigger,
                target_type,
                target_id,
            )
            return False

        await self.execute(
            """
            INSERT INTO autoresponder_exclusive (guild_id, trigger, target_type, target_id)
            VALUES ($1, $2, $3, $4)
            """,
            guild_id,
            trigger,
            target_type,
            target_id,
        )
        return True

    async def list_autoresponder_exclusives(
        self,
        guild_id: int,
        trigger: str,
    ) -> list[Row]:
        """list exclusive role and channel targets for one autoresponder"""
        return await self.fetch(
            """
            SELECT target_type, target_id
            FROM autoresponder_exclusive
            WHERE guild_id = $1 AND trigger = $2
            ORDER BY target_type, target_id
            """,
            guild_id,
            trigger,
        )

    async def toggle_autoresponder_role(
        self,
        guild_id: int,
        trigger: str,
        role_id: int,
        mode: str,
    ) -> bool:
        """toggle a role add or remove action for one autoresponder"""
        existing = await self.fetchrow(
            """
            SELECT 1
            FROM autoresponder_roles
            WHERE guild_id = $1 AND trigger = $2 AND role_id = $3 AND mode = $4
            """,
            guild_id,
            trigger,
            role_id,
            mode,
        )
        if existing:
            await self.execute(
                """
                DELETE FROM autoresponder_roles
                WHERE guild_id = $1 AND trigger = $2 AND role_id = $3 AND mode = $4
                """,
                guild_id,
                trigger,
                role_id,
                mode,
            )
            return False

        await self.execute(
            """
            INSERT INTO autoresponder_roles (guild_id, trigger, role_id, mode)
            VALUES ($1, $2, $3, $4)
            """,
            guild_id,
            trigger,
            role_id,
            mode,
        )
        return True

    async def list_autoresponder_roles(
        self,
        guild_id: int,
        trigger: str,
        mode: str,
    ) -> list[int]:
        """list role ids configured for one autoresponder mode"""
        rows = await self.fetch(
            """
            SELECT role_id
            FROM autoresponder_roles
            WHERE guild_id = $1 AND trigger = $2 AND mode = $3
            ORDER BY role_id
            """,
            guild_id,
            trigger,
            mode,
        )
        return [int(row.role_id) for row in rows]

    async def list_autoresponder_role_triggers(self, guild_id: int) -> list[str]:
        """list distinct triggers that have role actions configured"""
        rows = await self.fetch(
            """
            SELECT DISTINCT trigger
            FROM autoresponder_roles
            WHERE guild_id = $1
            ORDER BY trigger
            """,
            guild_id,
        )
        return [str(row.trigger) for row in rows]

    async def migrate(self) -> Optional[bool]:
        """run pending sql migration files"""
        if await self.fetchval("SELECT count(*) FROM pokemon.users") > 10:
            log.info("no migrations needed")
            return
        files = sorted(
            glob.glob("var/migration_*.sql"),
            key=lambda x: int(x.split("_")[-1].split(".")[0]),
        )
        combined = "".join(open(f).read() for f in files)
        with open("var/migrations.sql", "w") as f:
            f.write(combined)
        return True

    async def purge(self, column: str, value: Any) -> None:
        """delete value from all matching tables"""
        tables = [
            r.table_name
            for r in await self.fetch(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = $1",
                column,
            )
        ]
        await asyncio.gather(*[
            self.execute(f"DELETE FROM {t} WHERE {column} = $1", value)
            for t in tables
        ])

    async def purge_guild_data(self, guild_id: int) -> None:
        """delete every row that belongs to one guild"""
        await self.purge("guild_id", guild_id)
