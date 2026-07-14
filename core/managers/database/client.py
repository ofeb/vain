"""database connection pool.
wraps asyncpg with basic caching built in.
use fetch fetchrow fetchval or execute"""

from __future__ import annotations
from datetime import datetime
import asyncio, contextlib, glob, json, re
from logging import getLogger
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable, Optional, Protocol, Sequence, Union
from urllib.parse import unquote, urlsplit
import ujson
from asyncpg import Connection, Pool, Record as BaseRecord, create_pool
from asyncpg.exceptions import InvalidCatalogNameError
from discord.ext.commands import Context, check
from ..values import database
from ..app_emojis import default_emoji
from ..filetypes import POSTGRES_DB_FILE, ensure_storage_files

log = getLogger(__name__)


def query_limit(table: str, limit: int = 5):
    async def predicate(ctx: Context):
        count = await ctx.bot.db.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE guild_id = $1", ctx.guild.id
        )
        if count == limit:
            await ctx.fail(f"**can't** make more than **{limit}** {table}s")
            return False
        return True
    return check(predicate)


class Row(BaseRecord):
    def __getattr__(self, name: Union[str, Any]) -> Any:
        return self[name]
    def __dict__(self) -> dict:
        return dict(self)
    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self else default


class ConnProto(Protocol):
    async def __aenter__(self) -> Connection: ...
    async def __aexit__(self, et, ev, tb) -> None: ...


class Database:
    """postgres pool wrapper with cache"""

    def __init__(self):
        self.uri: str = database.dsn
        self.pool: Optional[Pool] = None
        self.cache: dict = {}

    def _encode(self, value: Any) -> str:
        """serialize json/jsonb values for asyncpg.

        some callers already pass serialized json strings while others pass
        python dict/list values directly. keep both working.
        """
        if isinstance(value, str):
            return value
        return ujson.dumps(value)

    def _decode(self, value: Any) -> Any:
        """deserialize json/jsonb values returned by asyncpg."""
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            return ujson.loads(value)
        return value

    async def _init_conn(self, conn: Connection) -> None:
        for name in ("json", "jsonb"):
            await conn.set_type_codec(
                name,
                encoder=self._encode,
                decoder=self._decode,
                schema="pg_catalog",
            )

    async def _make_pool(self) -> Pool:
        pool = await create_pool(
            dsn=self.uri,
            init=self._init_conn,
            record_class=Row,
            min_size=1,
            max_size=5,
        )
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
        ensure_storage_files(postgres=True, redis=False)
        log.info("postgres.db storage file at %s", POSTGRES_DB_FILE)

        user, pw, host, port, name = self._dsn_parts(self.uri)
        log.info("connecting to postgres at %s:%s/%s", host, port, name)
        try:
            self.pool = await self._make_pool()
        except InvalidCatalogNameError:
            log.warning("database %s missing, creating", name)
            await asyncio.to_thread(self._create_db, name, user, pw, host, port)
            self.pool = await self._make_pool()
        try:
            await self.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        except Exception as e:
            log.warning(f"timescaledb not available: {e}")
        await self._run_schema()
        log.info("postgres pool ready")
        return self.pool

    async def _run_schema(self) -> None:
        """Execute schema.sql to create/update all tables."""
        schema_path = Path(__file__).parent / "models" / "schema.sql"
        if not schema_path.exists():
            log.warning("schema.sql not found at %s", schema_path)
            return
        try:
            sql = schema_path.read_text(encoding="utf-8")
            async with self.pool.acquire() as conn:
                await conn.execute(sql)
            log.info("schema.sql applied successfully")
        except Exception as e:
            log.error("Failed to apply schema.sql: %s", e)

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

    async def set_lastfm_login(self, token: str, user_id: int) -> None:
        """store a pending Last.fm login token"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_logins (token, user_id)
            VALUES ($1, $2)
            ON CONFLICT (token) DO UPDATE SET user_id = EXCLUDED.user_id
            """,
            token,
            user_id,
        )

    async def consume_lastfm_login(self, token: str) -> int | None:
        """consume a Last.fm login token once authorized"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            "SELECT user_id FROM lastfm_logins WHERE token = $1 AND used_at IS NULL",
            token,
            cached=False,
        )
        if not row:
            return None
        await self.execute(
            "UPDATE lastfm_logins SET used_at = NOW() WHERE token = $1",
            token,
        )
        return row["user_id"]

    async def get_lastfm_login_user(self, token: str) -> int | None:
        """fetch the owner of a stored Last.fm login token"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            "SELECT user_id FROM lastfm_logins WHERE token = $1",
            token,
        )
        return row["user_id"] if row else None

    async def mark_lastfm_login_used(self, token: str) -> None:
        """mark a Last.fm login token as consumed"""
        if not self.pool:
            return
        await self.execute(
            "UPDATE lastfm_logins SET used_at = NOW() WHERE token = $1",
            token,
        )

    async def set_lastfm_user(
        self,
        user_id: int,
        username: str,
        session_key: str | None,
    ) -> None:
        """upsert a linked Last.fm account"""
        if not self.pool:
            return
        existing = await self.fetchrow(
            "SELECT lastfm_username FROM lastfm_users WHERE user_id = $1",
            user_id,
            cached=False,
        )
        await self.execute(
            """
            INSERT INTO lastfm_users (user_id, lastfm_username, session_key)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id)
            DO UPDATE SET
                lastfm_username = EXCLUDED.lastfm_username,
                session_key = EXCLUDED.session_key,
                updated_at = NOW()
            """,
            user_id,
            username,
            session_key,
        )
        await self.execute(
            """
            INSERT INTO lastfm (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET username = EXCLUDED.username
            """,
            user_id,
            username,
        )
        if existing and existing["lastfm_username"] != username:
            await self.execute(
                "DELETE FROM lastfm_library_profiles WHERE user_id = $1",
                user_id,
            )
            await self.execute(
                "DELETE FROM lastfm_library_artists WHERE user_id = $1",
                user_id,
            )
            await self.execute(
                "DELETE FROM lastfm_library_albums WHERE user_id = $1",
                user_id,
            )
            await self.execute(
                "DELETE FROM lastfm_library_tracks WHERE user_id = $1",
                user_id,
            )

    async def get_lastfm_user(self, user_id: int) -> dict | None:
        """fetch a linked Last.fm account"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            """
            SELECT user_id, lastfm_username, session_key
            FROM lastfm_users
            WHERE user_id = $1
            """,
            user_id,
        )
        if row:
            return dict(row)
        legacy = await self.fetchrow(
            "SELECT user_id, username FROM lastfm WHERE user_id = $1",
            user_id,
        )
        if not legacy or not legacy["username"]:
            return None
        return {
            "user_id": legacy["user_id"],
            "lastfm_username": legacy["username"],
            "session_key": None,
        }

    async def get_lastfm_users(self) -> list[dict]:
        """list all linked Last.fm accounts"""
        if not self.pool:
            return []
        rows = await self.fetch(
            """
            SELECT user_id, lastfm_username
            FROM lastfm_users
            UNION
            SELECT user_id, username AS lastfm_username
            FROM lastfm
            WHERE COALESCE(username, '') <> ''
              AND user_id NOT IN (SELECT user_id FROM lastfm_users)
            ORDER BY user_id
            """,
            cached=False,
        )
        return [dict(row) for row in rows]

    async def remove_lastfm_user(self, user_id: int) -> None:
        """remove a linked Last.fm account and its cached data"""
        if not self.pool:
            return
        await self.execute("DELETE FROM lastfm_users WHERE user_id = $1", user_id)
        await self.execute("DELETE FROM lastfm WHERE user_id = $1", user_id)
        await self.execute(
            "DELETE FROM lastfm_library_profiles WHERE user_id = $1",
            user_id,
        )
        await self.execute(
            "DELETE FROM lastfm_library_artists WHERE user_id = $1",
            user_id,
        )
        await self.execute(
            "DELETE FROM lastfm_library_albums WHERE user_id = $1",
            user_id,
        )
        await self.execute(
            "DELETE FROM lastfm_library_tracks WHERE user_id = $1",
            user_id,
        )
        await self.execute(
            "DELETE FROM lastfm_album_artwork WHERE user_id = $1",
            user_id,
        )
        await self.execute("DELETE FROM lastfm_crowns WHERE user_id = $1", user_id)
        await self.execute(
            """
            DELETE FROM lastfm_crown_history
            WHERE previous_user_id = $1 OR new_user_id = $1
            """,
            user_id,
        )

    async def set_lastfm_color(self, user_id: int, color: str | None) -> None:
        """set or clear a user's Last.fm color override"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_settings (user_id, color)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET color = EXCLUDED.color, updated_at = NOW()
            """,
            user_id,
            color,
        )

    async def get_lastfm_color(self, user_id: int) -> str | None:
        """fetch a user's Last.fm color override"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            "SELECT color FROM lastfm_settings WHERE user_id = $1",
            user_id,
        )
        return row["color"] if row else None

    async def set_lastfm_mode(self, user_id: int, mode: str | None) -> None:
        """set or clear a user's Last.fm nowplaying mode"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_settings (user_id, mode)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
            """,
            user_id,
            mode,
        )

    async def get_lastfm_mode(self, user_id: int) -> str | None:
        """fetch a user's Last.fm nowplaying mode"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            "SELECT mode FROM lastfm_settings WHERE user_id = $1",
            user_id,
        )
        return row["mode"] if row else None

    async def set_lastfm_reactions(
        self,
        user_id: int,
        upvote: str | None,
        downvote: str | None,
    ) -> None:
        """set or clear personal Last.fm reactions"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_settings (user_id, upvote, downvote)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id)
            DO UPDATE SET
                upvote = EXCLUDED.upvote,
                downvote = EXCLUDED.downvote,
                updated_at = NOW()
            """,
            user_id,
            upvote,
            downvote,
        )

    async def get_lastfm_reactions(self, user_id: int) -> dict | None:
        """fetch personal Last.fm reactions"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            "SELECT upvote, downvote FROM lastfm_settings WHERE user_id = $1",
            user_id,
        )
        return dict(row) if row else None

    async def set_lastfm_custom_embed(
        self,
        user_id: int,
        script: str | None,
        *,
        np_reply: bool = False,
    ) -> None:
        """set or clear a user's custom Last.fm embed"""
        if not self.pool:
            return
        effective_reply = bool(np_reply) if script else False
        await self.execute(
            """
            INSERT INTO lastfm_settings (user_id, custom_embed, np_reply)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id)
            DO UPDATE SET
                custom_embed = EXCLUDED.custom_embed,
                np_reply = EXCLUDED.np_reply,
                updated_at = NOW()
            """,
            user_id,
            script,
            effective_reply,
        )

    async def get_lastfm_custom_embed_settings(
        self,
        user_id: int,
    ) -> tuple[str | None, bool]:
        """fetch a user's custom Last.fm embed and reply flag"""
        if not self.pool:
            return None, False
        row = await self.fetchrow(
            """
            SELECT custom_embed, np_reply
            FROM lastfm_settings
            WHERE user_id = $1
            """,
            user_id,
        )
        if not row:
            return None, False
        return row["custom_embed"], bool(row["np_reply"])

    async def get_lastfm_custom_embed(self, user_id: int) -> str | None:
        """fetch a user's custom Last.fm embed only"""
        script, _ = await self.get_lastfm_custom_embed_settings(user_id)
        return script

    async def set_lastfm_guild_reactions(
        self,
        guild_id: int,
        upvote: str | None,
        downvote: str | None,
    ) -> None:
        """set or clear guild-wide Last.fm reactions"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_guild_settings (guild_id, upvote, downvote)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                upvote = EXCLUDED.upvote,
                downvote = EXCLUDED.downvote,
                updated_at = NOW()
            """,
            guild_id,
            upvote,
            downvote,
        )

    async def get_lastfm_guild_reactions(self, guild_id: int) -> dict | None:
        """fetch guild-wide Last.fm reactions"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            "SELECT upvote, downvote FROM lastfm_guild_settings WHERE guild_id = $1",
            guild_id,
        )
        return dict(row) if row else None

    async def set_lastfm_custom_command(
        self,
        guild_id: int,
        user_id: int,
        command: str,
    ) -> None:
        """set a custom nowplaying alias fragment for a member"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_custom_commands (guild_id, user_id, command)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET command = EXCLUDED.command, updated_at = NOW()
            """,
            guild_id,
            user_id,
            command,
        )

    async def get_lastfm_custom_command(
        self,
        guild_id: int,
        user_id: int,
    ) -> dict | None:
        """fetch a member's custom nowplaying command"""
        if not self.pool:
            return None
        row = await self.fetchrow(
            """
            SELECT command, public
            FROM lastfm_custom_commands
            WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id,
            user_id,
        )
        return dict(row) if row else None

    async def list_lastfm_custom_commands(self, guild_id: int) -> list[dict]:
        """list custom nowplaying commands for a guild"""
        if not self.pool:
            return []
        rows = await self.fetch(
            """
            SELECT user_id, command, public
            FROM lastfm_custom_commands
            WHERE guild_id = $1
            ORDER BY created_at ASC
            """,
            guild_id,
            cached=False,
        )
        return [dict(row) for row in rows]

    async def remove_lastfm_custom_command(self, guild_id: int, user_id: int) -> None:
        """remove one custom nowplaying command"""
        if not self.pool:
            return
        await self.execute(
            "DELETE FROM lastfm_custom_commands WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    async def reset_lastfm_custom_commands(self, guild_id: int) -> None:
        """remove all custom nowplaying commands for a guild"""
        if not self.pool:
            return
        await self.execute(
            "DELETE FROM lastfm_custom_commands WHERE guild_id = $1",
            guild_id,
        )

    async def set_lastfm_custom_public(
        self,
        guild_id: int,
        user_id: int,
        public: bool,
    ) -> None:
        """toggle whether a member's custom command is public"""
        if not self.pool:
            return
        await self.execute(
            """
            UPDATE lastfm_custom_commands
            SET public = $3, updated_at = NOW()
            WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id,
            user_id,
            public,
        )

    async def set_lastfm_blacklist(self, guild_id: int, user_id: int) -> None:
        """add a user to the Last.fm custom command blacklist"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_custom_blacklist (guild_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            guild_id,
            user_id,
        )

    async def remove_lastfm_blacklist(self, guild_id: int, user_id: int) -> None:
        """remove a user from the Last.fm custom command blacklist"""
        if not self.pool:
            return
        await self.execute(
            "DELETE FROM lastfm_custom_blacklist WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    async def list_lastfm_blacklist(self, guild_id: int) -> list[int]:
        """list blacklisted users for Last.fm custom commands"""
        if not self.pool:
            return []
        rows = await self.fetch(
            "SELECT user_id FROM lastfm_custom_blacklist WHERE guild_id = $1",
            guild_id,
            cached=False,
        )
        return [row["user_id"] for row in rows]

    async def set_lastfm_hidden(self, guild_id: int, user_id: int) -> None:
        """hide a member from guild whoknows results"""
        if not self.pool:
            return
        await self.execute(
            """
            INSERT INTO lastfm_hidden (guild_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            guild_id,
            user_id,
        )

    async def remove_lastfm_hidden(self, guild_id: int, user_id: int) -> None:
        """unhide a member from guild whoknows results"""
        if not self.pool:
            return
        await self.execute(
            "DELETE FROM lastfm_hidden WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    async def list_lastfm_hidden(self, guild_id: int) -> list[int]:
        """list members hidden from guild whoknows results"""
        if not self.pool:
            return []
        rows = await self.fetch(
            "SELECT user_id FROM lastfm_hidden WHERE guild_id = $1",
            guild_id,
            cached=False,
        )
        return [row["user_id"] for row in rows]

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
        """fetch one webhook row by the public vain identifier"""
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

    async def get_antinuke_log_channel(self, guild_id: int) -> int | None:
        """fetch the antinuke log channel id for a guild"""
        return await self.fetchval(
            "SELECT antinuke_log_channel_id FROM server_settings WHERE guild_id = $1",
            guild_id,
        )

    async def get_antiraid_log_channel(self, guild_id: int) -> int | None:
        """fetch the antiraid log channel id for a guild"""
        return await self.fetchval(
            "SELECT antiraid_log_channel_id FROM server_settings WHERE guild_id = $1",
            guild_id,
        )

    async def set_security_log_channels(
        self,
        guild_id: int,
        *,
        antinuke_channel_id: int | None = None,
        antiraid_channel_id: int | None = None,
    ) -> None:
        """upsert antinuke and antiraid log channel bindings"""
        await self.execute(
            """
            INSERT INTO server_settings (guild_id, antinuke_log_channel_id, antiraid_log_channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET
                antinuke_log_channel_id = COALESCE(EXCLUDED.antinuke_log_channel_id, server_settings.antinuke_log_channel_id),
                antiraid_log_channel_id = COALESCE(EXCLUDED.antiraid_log_channel_id, server_settings.antiraid_log_channel_id),
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            antinuke_channel_id,
            antiraid_channel_id,
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

    async def fetch_modlog_case(self, guild_id: int, case_id: int):
        return await self.fetchrow(
            """
            SELECT *
            FROM modlog_cases
            WHERE guild_id = $1 AND case_id = $2
            """,
            guild_id,
            case_id,
        )

    async def fetch_modlog_cases_for_user(
        self,
        guild_id: int,
        target_id: int,
        *,
        action: str | None = None,
        limit: int = 50,
    ):
        if action:
            return await self.fetch(
                """
                SELECT *
                FROM modlog_cases
                WHERE guild_id = $1 AND target_id = $2 AND action = $3
                ORDER BY case_id DESC
                LIMIT $4
                """,
                guild_id,
                target_id,
                action,
                limit,
                cached=False,
            )
        return await self.fetch(
            """
            SELECT *
            FROM modlog_cases
            WHERE guild_id = $1 AND target_id = $2
            ORDER BY case_id DESC
            LIMIT $3
            """,
            guild_id,
            target_id,
            limit,
            cached=False,
        )

    async def fetch_modlog_cases_by_moderator(
        self,
        guild_id: int,
        moderator_id: int,
        *,
        action: str | None = None,
        limit: int = 50,
    ):
        if action:
            return await self.fetch(
                """
                SELECT *
                FROM modlog_cases
                WHERE guild_id = $1 AND moderator_id = $2 AND action = $3
                ORDER BY case_id DESC
                LIMIT $4
                """,
                guild_id,
                moderator_id,
                action,
                limit,
                cached=False,
            )
        return await self.fetch(
            """
            SELECT *
            FROM modlog_cases
            WHERE guild_id = $1 AND moderator_id = $2
            ORDER BY case_id DESC
            LIMIT $3
            """,
            guild_id,
            moderator_id,
            limit,
            cached=False,
        )

    async def count_modlog_cases(
        self,
        guild_id: int,
        target_id: int,
        *,
        action: str | None = None,
    ) -> int:
        if action:
            return int(
                await self.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM modlog_cases
                    WHERE guild_id = $1 AND target_id = $2 AND action = $3
                    """,
                    guild_id,
                    target_id,
                    action,
                )
                or 0
            )
        return int(
            await self.fetchval(
                """
                SELECT COUNT(*)
                FROM modlog_cases
                WHERE guild_id = $1 AND target_id = $2
                """,
                guild_id,
                target_id,
            )
            or 0
        )

    async def add_hardban(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int | None,
        reason: str | None,
    ) -> None:
        await self.execute(
            """
            INSERT INTO hardbans (guild_id, user_id, moderator_id, reason)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET moderator_id = EXCLUDED.moderator_id,
                          reason = EXCLUDED.reason
            """,
            guild_id,
            user_id,
            moderator_id,
            reason,
        )

    async def remove_hardban(self, guild_id: int, user_id: int) -> None:
        await self.execute(
            "DELETE FROM hardbans WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    async def is_hardbanned(self, guild_id: int, user_id: int) -> bool:
        row = await self.fetchrow(
            "SELECT 1 FROM hardbans WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return row is not None

    async def fetch_hardbans(self, guild_id: int):
        return await self.fetch(
            """
            SELECT *
            FROM hardbans
            WHERE guild_id = $1
            ORDER BY created_at DESC
            """,
            guild_id,
            cached=False,
        )

    async def add_temprole(
        self,
        guild_id: int,
        user_id: int,
        role_id: int,
        expires_at,
        moderator_id: int | None,
    ) -> None:
        await self.execute(
            """
            INSERT INTO temproles (guild_id, user_id, role_id, expires_at, moderator_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id, user_id, role_id)
            DO UPDATE SET expires_at = EXCLUDED.expires_at,
                          moderator_id = EXCLUDED.moderator_id
            """,
            guild_id,
            user_id,
            role_id,
            expires_at,
            moderator_id,
        )

    async def remove_temprole(
        self,
        guild_id: int,
        user_id: int,
        role_id: int,
    ) -> None:
        await self.execute(
            """
            DELETE FROM temproles
            WHERE guild_id = $1 AND user_id = $2 AND role_id = $3
            """,
            guild_id,
            user_id,
            role_id,
        )

    async def fetch_temproles(self, guild_id: int):
        return await self.fetch(
            """
            SELECT *
            FROM temproles
            WHERE guild_id = $1
            ORDER BY expires_at ASC
            """,
            guild_id,
            cached=False,
        )

    async def fetch_due_temproles(self):
        return await self.fetch(
            """
            SELECT *
            FROM temproles
            WHERE expires_at <= CURRENT_TIMESTAMP
            ORDER BY expires_at
            """,
            cached=False,
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
        await self.purge("guild_id", guild_id)

    async def get_guild_customize(self, guild_id: int) -> dict:
        """Get guild customize settings"""
        row = await self.fetchrow(
            "SELECT emoji, color, voicemaster_emoji FROM guild_customize WHERE guild_id = $1",
            guild_id,
        )
        if not row:
            return {"emoji": {}, "color": {}, "voicemaster_emoji": {}}
        return {
            "emoji": self._decode(row.get("emoji")) or {},
            "color": self._decode(row.get("color")) or {},
            "voicemaster_emoji": self._decode(row.get("voicemaster_emoji")) or {},
        }

    async def set_guild_customize(self, guild_id: int, key: str, value: dict) -> None:
        """Set guild customize emoji/color"""
        if key not in {"emoji", "color", "voicemaster_emoji"}:
            raise ValueError(f"invalid guild customize key: {key}")
        await self.execute(
            f"""
            INSERT INTO guild_customize (guild_id, {key}, updated_at)
            VALUES ($1, $2::JSONB, CURRENT_TIMESTAMP)
            ON CONFLICT (guild_id) DO UPDATE SET
                {key} = EXCLUDED.{key},
                updated_at = CURRENT_TIMESTAMP
            """,
            guild_id,
            value,
        )

    async def reset_guild_customize(self, guild_id: int) -> None:
        """Remove all stored guild customize overrides."""
        await self.execute(
            "DELETE FROM guild_customize WHERE guild_id = $1",
            guild_id,
        )

    async def get_user_customize(self, user_id: int, guild_id: int) -> dict:
        """Get user customize settings"""
        row = await self.fetchrow(
            "SELECT emoji, color FROM user_customize WHERE user_id = $1 AND guild_id = $2",
            user_id,
            guild_id,
        )
        if not row:
            return {"emoji": {}, "color": {}}
        return {
            "emoji": self._decode(row.get("emoji")) or {},
            "color": self._decode(row.get("color")) or {},
        }

    async def set_user_customize(self, user_id: int, guild_id: int, key: str, value: dict) -> None:
        """Set user customize emoji/color"""
        if key not in {"emoji", "color"}:
            raise ValueError(f"invalid user customize key: {key}")
        await self.execute(
            f"""
            INSERT INTO user_customize (user_id, guild_id, {key}, updated_at)
            VALUES ($1, $2, $3::JSONB, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, guild_id) DO UPDATE SET
                {key} = EXCLUDED.{key},
                updated_at = CURRENT_TIMESTAMP
            """,
            user_id,
            guild_id,
            value,
        )

    async def reset_user_customize(self, user_id: int, guild_id: int) -> None:
        """Remove all stored user customize overrides."""
        await self.execute(
            "DELETE FROM user_customize WHERE user_id = $1 AND guild_id = $2",
            user_id,
            guild_id,
        )

    async def get_emoji(self, guild_id: int | None, user_id: int | None = None) -> dict:
        """Get emojis with guild/user override"""
        default_emoji_map = {
            "success": default_emoji("approve", "<:approve_new:1526186163457490974>"),
            "warn": default_emoji("warn", "<:warning:1526186228561477642>"),
            "deny": default_emoji("deny", "<:deny:1526186193971052634>"),
            "cooldown": default_emoji("cooldown", "<:cooldown:1525919040776835075>"),
            "loading": default_emoji("loading", "<a:embeds_loading:1511705994823077988>"),
            "info": "<:interface_information:1511705999550185646>",
        }

        result = dict(default_emoji_map)

        if guild_id:
            guild_settings = await self.get_guild_customize(guild_id)
            result.update(guild_settings.get("emoji", {}))

        if user_id is not None and guild_id is not None:
            user_settings = await self.get_user_customize(user_id, guild_id)
            result.update(user_settings.get("emoji", {}))

        return result

    async def get_color(self, guild_id: int, user_id: int = None) -> dict:
        """Get colors with guild/user override"""
        default_color = {
            "base": 0xC8A4C2,
            "approve": 0xA8D8A8,
            "warn": 0xF5D76E,
            "deny": 0xE07A7A,
            "cooldown": 0xBBA0D2,
            "settings": 0xD4B8D0,
            "dark": 0x9B7A9E,
        }

        guild_settings = await self.get_guild_customize(guild_id)
        guild_color = guild_settings.get("color", {})
        for k, v in guild_color.items():
            if isinstance(v, str):
                try:
                    guild_color[k] = int(v, 16)
                except ValueError:
                    pass

        result = {**default_color, **guild_color}

        if user_id:
            user_settings = await self.get_user_customize(user_id, guild_id)
            user_color = user_settings.get("color", {})
            for k, v in user_color.items():
                if isinstance(v, str):
                    try:
                        user_color[k] = int(v, 16)
                    except ValueError:
                        pass
            result.update(user_color)

        return result

    async def get_vm_emoji(self, guild_id: int) -> dict:
        """Get voicemaster emojis"""
        default_vm = {
            "lock": "<:interface_lock:1511706000007106721>",
            "unlock": "<:interface_unlock:1511706000690774097>",
            "ghost": "<:interface_ghost:1511705999264710756>",
            "reveal": "<:interface_reveal:1511706000405692449>",
            "claim": "<:interface_claim:1511705997897633954>",
            "disconnect": "<:interface_disconnect:1511705999264972800>",
            "activity": "<:interface_activity:1511705997889114273>",
            "increase": "<:interface_increase:1511705999348596767>",
            "decrease": "<:interface_decrease:1511705998434500719>",
        }

        guild_settings = await self.get_guild_customize(guild_id)
        vm_emoji = guild_settings.get("voicemaster_emoji", {})
        return {**default_vm, **vm_emoji}
