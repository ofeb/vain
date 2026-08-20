from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.voicemaster.settings')


class Record(TypedDict, total=False):
    """DB row for `voicemaster_configuration`."""

    guild_id: int
    channel_id: Any | None
    category_id: Any | None
    interface_id: Any | None
    panel_message_id: Any | None
    private_category_id: Any | None
    role_id: Any | None
    bitrate: Any | None
    region: Any | None
    send_interface: bool
    default_name: Any | None
    join_role_id: Any | None
    default_status_text: Any | None
    default_status_emoji: Any | None
    deny_messages: bool
    use_private: bool


class Settings:
    """Guild settings for `voicemaster_configuration`."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]

    def __init__(self, bot: Vain, guild: Guild, record: dict[str, Any]) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return self.record.get('channel_id') is not None

    @property
    def channel_id(self) -> Any | None:
        return self.record.get('channel_id')

    @property
    def category_id(self) -> Any | None:
        return self.record.get('category_id')

    @property
    def interface_id(self) -> Any | None:
        return self.record.get('interface_id')

    @property
    def panel_message_id(self) -> Any | None:
        return self.record.get('panel_message_id')

    @property
    def private_category_id(self) -> Any | None:
        return self.record.get('private_category_id')

    @property
    def role_id(self) -> Any | None:
        return self.record.get('role_id')

    @property
    def bitrate(self) -> Any | None:
        return self.record.get('bitrate')

    @property
    def region(self) -> Any | None:
        return self.record.get('region')

    @property
    def send_interface(self) -> bool:
        return bool(self.record.get('send_interface', True))

    @property
    def default_name(self) -> Any | None:
        return self.record.get('default_name')

    @property
    def join_role_id(self) -> Any | None:
        return self.record.get('join_role_id')

    @property
    def default_status_text(self) -> Any | None:
        return self.record.get('default_status_text')

    @property
    def default_status_emoji(self) -> Any | None:
        return self.record.get('default_status_emoji')

    @property
    def deny_messages(self) -> bool:
        return bool(self.record.get('deny_messages', False))

    @property
    def use_private(self) -> bool:
        return bool(self.record.get('use_private', False))

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('channel_id')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @property
    def role(self) -> Role | None:
        rid = self.record.get('role_id')
        if not rid:
            return None
        return self.guild.get_role(int(rid))

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'channel_id': None,
            'category_id': None,
            'interface_id': None,
            'panel_message_id': None,
            'private_category_id': None,
            'role_id': None,
            'bitrate': None,
            'region': None,
            'send_interface': True,
            'default_name': None,
            'join_role_id': None,
            'default_status_text': None,
            'default_status_emoji': None,
            'deny_messages': False,
            'use_private': False,
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM voicemaster_configuration WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'channel_id': kwargs.get('channel_id', self.channel_id),
            'category_id': kwargs.get('category_id', self.category_id),
            'interface_id': kwargs.get('interface_id', self.interface_id),
            'panel_message_id': kwargs.get('panel_message_id', self.panel_message_id),
            'private_category_id': kwargs.get('private_category_id', self.private_category_id),
            'role_id': kwargs.get('role_id', self.role_id),
            'bitrate': kwargs.get('bitrate', self.bitrate),
            'region': kwargs.get('region', self.region),
            'send_interface': kwargs.get('send_interface', self.send_interface),
            'default_name': kwargs.get('default_name', self.default_name),
            'join_role_id': kwargs.get('join_role_id', self.join_role_id),
            'default_status_text': kwargs.get('default_status_text', self.default_status_text),
            'default_status_emoji': kwargs.get('default_status_emoji', self.default_status_emoji),
            'deny_messages': kwargs.get('deny_messages', self.deny_messages),
            'use_private': kwargs.get('use_private', self.use_private),
        }
        query = """
        INSERT INTO voicemaster_configuration (guild_id, channel_id, category_id, interface_id, panel_message_id, private_category_id, role_id, bitrate, region, send_interface, default_name, join_role_id, default_status_text, default_status_emoji, deny_messages, use_private)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            category_id = EXCLUDED.category_id,
            interface_id = EXCLUDED.interface_id,
            panel_message_id = EXCLUDED.panel_message_id,
            private_category_id = EXCLUDED.private_category_id,
            role_id = EXCLUDED.role_id,
            bitrate = EXCLUDED.bitrate,
            region = EXCLUDED.region,
            send_interface = EXCLUDED.send_interface,
            default_name = EXCLUDED.default_name,
            join_role_id = EXCLUDED.join_role_id,
            default_status_text = EXCLUDED.default_status_text,
            default_status_emoji = EXCLUDED.default_status_emoji,
            deny_messages = EXCLUDED.deny_messages,
            use_private = EXCLUDED.use_private
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['channel_id'],
            values['category_id'],
            values['interface_id'],
            values['panel_message_id'],
            values['private_category_id'],
            values['role_id'],
            values['bitrate'],
            values['region'],
            values['send_interface'],
            values['default_name'],
            values['join_role_id'],
            values['default_status_text'],
            values['default_status_emoji'],
            values['deny_messages'],
            values['use_private'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert voicemaster_configuration guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM voicemaster_configuration WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    

    @staticmethod
    async def ensure_schema(db) -> None:
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_configuration ADD COLUMN IF NOT EXISTS panel_message_id BIGINT"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_configuration ADD COLUMN IF NOT EXISTS default_status_text TEXT"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_configuration ADD COLUMN IF NOT EXISTS default_status_emoji TEXT"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                """CREATE TABLE IF NOT EXISTS voicemaster_join2unmute (
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )"""
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_channels ADD COLUMN IF NOT EXISTS status_text TEXT"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_channels ADD COLUMN IF NOT EXISTS status_emoji TEXT"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                """CREATE TABLE IF NOT EXISTS voicemaster_bans (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    banned_by BIGINT,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_configuration ADD COLUMN IF NOT EXISTS deny_messages BOOLEAN DEFAULT FALSE"
            )
        with contextlib.suppress(Exception):
            await db.execute(
                "ALTER TABLE voicemaster_configuration ADD COLUMN IF NOT EXISTS use_private BOOLEAN DEFAULT FALSE"
            )

    

    @staticmethod
    async def fetch_config_row(db, guild_id: int) -> dict[str, Any] | None:
        row = await db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1",
            guild_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def fetch_existing_config(db, guild_id: int) -> dict[str, Any] | None:
        row = await db.fetchrow(
            "SELECT category_id, interface_id, channel_id FROM voicemaster_configuration WHERE guild_id = $1",
            guild_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def delete_config_returning(db, guild_id: int) -> dict[str, Any] | None:
        row = await db.fetchrow(
            "DELETE FROM voicemaster_configuration WHERE guild_id = $1 RETURNING category_id, interface_id, channel_id",
            guild_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def delete_config_returning_category(db, guild_id: int) -> int | None:
        row = await db.fetchrow(
            "DELETE FROM voicemaster_configuration WHERE guild_id = $1 RETURNING category_id",
            guild_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def update_config_field(db, guild_id: int, field: str, value: Any) -> None:
        await db.execute(
            f"UPDATE voicemaster_configuration SET {field} = $2 WHERE guild_id = $1",
            guild_id, value,
        )

    @staticmethod
    async def get_config(db, guild_id: int) -> dict[str, Any] | None:
        row = await db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1", guild_id,
        )
        return dict(row) if row else None

    @staticmethod
    async def fetch_all_panel_rows(db) -> list[dict[str, Any]]:
        rows = await db.fetch(
            "SELECT guild_id, interface_id, panel_message_id FROM voicemaster_configuration"
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def fetch_interface_id(db, guild_id: int) -> int | None:
        row = await db.fetchrow(
            "SELECT interface_id FROM voicemaster_configuration WHERE guild_id = $1",
            guild_id,
        )
        return dict(row) if row else None

    

    @staticmethod
    async def insert_channel(db, guild_id: int, channel_id: int, owner_id: int) -> None:
        await db.execute(
            "INSERT INTO voicemaster_channels (guild_id, channel_id, owner_id) VALUES ($1, $2, $3)",
            guild_id, channel_id, owner_id,
        )

    @staticmethod
    async def update_channel_status(db, channel_id: int, status_text: str, status_emoji: str) -> None:
        await db.execute(
            "UPDATE voicemaster_channels SET status_text = $1, status_emoji = $2 WHERE channel_id = $3",
            status_text, status_emoji, channel_id,
        )

    @staticmethod
    async def get_channel_owner(db, channel_id: int) -> int | None:
        return await db.fetchval(
            "SELECT owner_id FROM voicemaster_channels WHERE channel_id = $1",
            channel_id,
        )

    @staticmethod
    async def update_channel_owner(db, channel_id: int, owner_id: int) -> None:
        await db.execute(
            "UPDATE voicemaster_channels SET owner_id = $2 WHERE channel_id = $1",
            channel_id, owner_id,
        )

    @staticmethod
    async def update_channel_field(db, channel_id: int, field: str, value: Any) -> None:
        await db.execute(
            f"UPDATE voicemaster_channels SET {field} = $2 WHERE channel_id = $1",
            channel_id, value,
        )

    @staticmethod
    async def fetch_all_channel_ids(db) -> list[dict[str, Any]]:
        rows = await db.fetch("SELECT channel_id FROM voicemaster_channels")
        return [dict(r) for r in rows]

    @staticmethod
    async def delete_empty_channels(db, channel_ids: list[int]) -> None:
        if channel_ids:
            await db.executemany(
                "DELETE FROM voicemaster_channels WHERE channel_id = $1",
                [(cid,) for cid in channel_ids]
            )

    @staticmethod
    async def fetch_guild_channel_ids(db, guild_id: int) -> set[int]:
        rows = await db.fetch(
            "SELECT channel_id FROM voicemaster_channels WHERE guild_id = $1",
            guild_id,
        )
        return {r["channel_id"] for r in rows}

    @staticmethod
    async def delete_channel(db, channel_id: int) -> int | None:
        return await db.fetchval(
            "DELETE FROM voicemaster_channels WHERE channel_id = $1 RETURNING owner_id",
            channel_id,
        )

    

    @staticmethod
    async def check_join2unmute(db, guild_id: int, channel_id: int) -> bool:
        return bool(
            await db.fetchrow(
                "SELECT channel_id FROM voicemaster_join2unmute WHERE guild_id = $1 AND channel_id = $2",
                guild_id, channel_id,
            )
        )

    @staticmethod
    async def toggle_join2unmute(db, guild_id: int, channel_id: int) -> bool:
        """Toggle join2unmute. Returns True if added, False if removed."""
        existing = await db.fetchrow(
            "SELECT channel_id FROM voicemaster_join2unmute WHERE guild_id = $1 AND channel_id = $2",
            guild_id, channel_id,
        )
        if existing:
            await db.execute(
                "DELETE FROM voicemaster_join2unmute WHERE guild_id = $1 AND channel_id = $2",
                guild_id, channel_id,
            )
            return False
        else:
            await db.execute(
                "INSERT INTO voicemaster_join2unmute (guild_id, channel_id) VALUES ($1, $2)",
                guild_id, channel_id,
            )
            return True

    

    @staticmethod
    async def check_ban(db, guild_id: int, user_id: int):
        return await db.fetchrow(
            "SELECT user_id, banned_by FROM voicemaster_bans WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    @staticmethod
    async def insert_ban(db, guild_id: int, user_id: int, banned_by: int) -> None:
        await db.execute(
            "INSERT INTO voicemaster_bans (guild_id, user_id, banned_by) VALUES ($1, $2, $3)",
            guild_id, user_id, banned_by,
        )

    @staticmethod
    async def remove_ban(db, guild_id: int, user_id: int) -> bool:
        return bool(
            await db.fetchval(
                "DELETE FROM voicemaster_bans WHERE guild_id = $1 AND user_id = $2 RETURNING user_id",
                guild_id, user_id,
            )
        )

    @staticmethod
    async def get_bans(db, guild_id: int) -> list[dict[str, Any]]:
        rows = await db.fetch(
            "SELECT user_id FROM voicemaster_bans WHERE guild_id = $1", guild_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def fetch_voice_config(db, guild_id: int) -> dict[str, Any] | None:
        row = await db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1",
            guild_id,
        )
        return dict(row) if row else None


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
