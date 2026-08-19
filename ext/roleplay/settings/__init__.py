from __future__ import annotations

from logging import getLogger
from typing import Any, TypedDict, cast

from discord import Guild
from discord import TextChannel, Thread, Role

from core.vain import Vain

logger = getLogger('vain.roleplay.settings')


class Record(TypedDict, total=False):
    """DB row for `roleplay_config`."""

    guild_id: int
    enabled: bool
    action_prefix: str
    action_channel: Any | None
    delete_original: bool
    character_tracking: bool
    character_cards: bool
    card_emoji: str


class Settings:
    """Guild settings for `roleplay_config`."""

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
    def action_prefix(self) -> str:
        return self.record.get('action_prefix', '*')

    @property
    def action_channel(self) -> Any | None:
        return self.record.get('action_channel')

    @property
    def delete_original(self) -> bool:
        return bool(self.record.get('delete_original', False))

    @property
    def character_tracking(self) -> bool:
        return bool(self.record.get('character_tracking', False))

    @property
    def character_cards(self) -> bool:
        return bool(self.record.get('character_cards', False))

    @property
    def card_emoji(self) -> str:
        return self.record.get('card_emoji', '🎭')

    @property
    def channel(self) -> TextChannel | Thread | None:
        cid = self.record.get('action_channel')
        if not cid:
            return None
        ch = self.guild.get_channel_or_thread(int(cid))
        return ch if isinstance(ch, (TextChannel, Thread)) else None

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "guild_id": 0,
            'enabled': False,
            'action_prefix': '*',
            'action_channel': None,
            'delete_original': False,
            'character_tracking': False,
            'character_cards': False,
            'card_emoji': '🎭',
        }

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM roleplay_config WHERE guild_id = $1",
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
                "SELECT EXISTS(SELECT 1 FROM roleplay_config WHERE guild_id = $1)",
                guild.id,
            )
        )

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        values = {
            "guild_id": self.guild.id,
            'enabled': kwargs.get('enabled', self.enabled),
            'action_prefix': kwargs.get('action_prefix', self.action_prefix),
            'action_channel': kwargs.get('action_channel', self.action_channel),
            'delete_original': kwargs.get('delete_original', self.delete_original),
            'character_tracking': kwargs.get('character_tracking', self.character_tracking),
            'character_cards': kwargs.get('character_cards', self.character_cards),
            'card_emoji': kwargs.get('card_emoji', self.card_emoji),
        }
        query = """
        INSERT INTO roleplay_config (guild_id, enabled, action_prefix, action_channel, delete_original, character_tracking, character_cards, card_emoji)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (guild_id) DO UPDATE SET
            enabled = EXCLUDED.enabled,
            action_prefix = EXCLUDED.action_prefix,
            action_channel = EXCLUDED.action_channel,
            delete_original = EXCLUDED.delete_original,
            character_tracking = EXCLUDED.character_tracking,
            character_cards = EXCLUDED.character_cards,
            card_emoji = EXCLUDED.card_emoji
        RETURNING *
        """
        record = await self.bot.db.fetchrow(
            query,
            values['guild_id'],
            values['enabled'],
            values['action_prefix'],
            values['action_channel'],
            values['delete_original'],
            values['character_tracking'],
            values['character_cards'],
            values['card_emoji'],
        )
        if record is not None:
            self.record = dict(record)
        else:
            self.record = values
        if revalidate:
            logger.debug("upsert roleplay_config guild=%s keys=%s", self.guild.id, list(kwargs))
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)

    async def delete(self) -> None:
        await self.bot.db.execute(
            "DELETE FROM roleplay_config WHERE guild_id = $1",
            self.guild.id,
        )
        data = self._default_config()
        data["guild_id"] = self.guild.id
        self.record = data

    @staticmethod
    async def record_action(db: Any, action: str, giver_id: int, receiver_id: int) -> int:
        return await db.fetchval(
            """
            INSERT INTO roleplay.actions (action, giver, receiver, amount)
                VALUES ($1, $2, $3, 1)
            ON CONFLICT (action, giver, receiver)
                DO UPDATE SET amount = roleplay.actions.amount + 1
            RETURNING amount
            """,
            action,
            giver_id,
            receiver_id,
            cached=False,
        )


async def fetch(bot: Vain, guild: Guild) -> Settings:
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    settings = await Settings.fetch(bot, guild)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild, **kwargs: Any) -> Settings:
    return await upsert(bot, guild, **kwargs)


__all__ = ["Settings", "Record", "fetch", "upsert", "insert"]
