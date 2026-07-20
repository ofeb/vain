from __future__ import annotations

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
    private_category_id: Any | None
    role_id: Any | None
    bitrate: Any | None
    region: Any | None
    send_interface: bool
    default_name: Any | None
    join_role_id: Any | None


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
            'private_category_id': None,
            'role_id': None,
            'bitrate': None,
            'region': None,
            'send_interface': True,
            'default_name': None,
            'join_role_id': None,
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
            'private_category_id': kwargs.get('private_category_id', self.private_category_id),
            'role_id': kwargs.get('role_id', self.role_id),
            'bitrate': kwargs.get('bitrate', self.bitrate),
            'region': kwargs.get('region', self.region),
            'send_interface': kwargs.get('send_interface', self.send_interface),
            'default_name': kwargs.get('default_name', self.default_name),
            'join_role_id': kwargs.get('join_role_id', self.join_role_id),
        }
        query = """
        INSERT INTO voicemaster_configuration (guild_id, channel_id, category_id, interface_id, private_category_id, role_id, bitrate, region, send_interface, default_name, join_role_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            category_id = EXCLUDED.category_id,
            interface_id = EXCLUDED.interface_id,
            private_category_id = EXCLUDED.private_category_id,
            role_id = EXCLUDED.role_id,
            bitrate = EXCLUDED.bitrate,
            region = EXCLUDED.region,
            send_interface = EXCLUDED.send_interface,
            default_name = EXCLUDED.default_name,
            join_role_id = EXCLUDED.join_role_id
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['channel_id'],
            values['category_id'],
            values['interface_id'],
            values['private_category_id'],
            values['role_id'],
            values['bitrate'],
            values['region'],
            values['send_interface'],
            values['default_name'],
            values['join_role_id'],
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


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
