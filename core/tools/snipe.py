from __future__ import annotations

"""In-memory snipe store: deleted, edited, and reaction removals per channel."""

import datetime
import typing
from collections import deque
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.vain import Vain


class SnipeError(Exception):
    """No snipe entry found."""


_PREFIX = {
    "snipe": "s-",
    "editsnipe": "es-",
    "reactionsnipe": "rs-",
    "rs": "rs-",
    "s": "s-",
    "es": "es-",
}


class Snipe:
    """Last 100 deleted / edited / reaction-removed entries per channel."""

    def __init__(self, bot: Vain) -> None:
        self.bot = bot
        self.data: dict[str, deque] = {}

    def _key(self, prefix: str, channel_id: int) -> str:
        return f"{prefix}{int(channel_id)}"

    def _store(self, key: str, entry: dict) -> None:
        if key not in self.data:
            self.data[key] = deque(maxlen=100)
        self.data[key].appendleft(entry)

    def _prefix(self, kind: str) -> str:
        return _PREFIX.get((kind or "snipe").lower(), "s-")

    async def add_entry(
        self,
        kind: str,
        message: typing.Union[discord.Message, tuple],
    ) -> dict:
        """Store a snipe entry for a channel."""
        kind_l = (kind or "snipe").lower()
        now_ts = datetime.datetime.utcnow().timestamp()

        if isinstance(message, discord.Message):
            author = message.author
            entry = {
                
                "timestamp": now_ts,
                "created_at": message.created_at.timestamp()
                if message.created_at
                else now_ts,
                "content": message.content or "",
                "embeds": [
                    e.to_dict()
                    for e in message.embeds[:8]
                    if e.type not in ("image", "video")
                ],
                "attachments": [
                    a.proxy_url or a.url for a in message.attachments
                ]
                + [
                    (e.thumbnail or e.image).url
                    for e in message.embeds
                    if e.type == "image" and (e.thumbnail or e.image)
                ],
                "stickers": [str(s.url) for s in message.stickers if getattr(s, "url", None)],
                "author": {
                    "id": author.id,
                    "name": getattr(author, "display_name", None) or author.name,
                    "avatar": str(author.display_avatar.url)
                    if author.display_avatar
                    else "",
                },
            }
            self._store(self._key(self._prefix(kind_l), message.channel.id), entry)
            return entry

        
        msg, reaction, user = message
        channel = getattr(msg, "channel", None)
        channel_id = getattr(channel, "id", None) if channel is not None else None
        if channel_id is None:
            return {}
        entry = {
            "timestamp": now_ts,
            "message": getattr(msg, "jump_url", ""),
            "reaction": str(reaction),
            "author": {
                "id": user.id,
                "name": getattr(user, "display_name", None) or user.name,
                "avatar": str(user.display_avatar.url)
                if getattr(user, "display_avatar", None)
                else "",
            },
        }
        self._store(self._key("rs-", channel_id), entry)
        return entry

    async def add_reaction_history(
        self, payload: discord.RawReactionActionEvent
    ) -> bool:
        """Log reaction removal to the database (best-effort)."""
        if self.bot.user and payload.user_id == self.bot.user.id:
            return False
        try:
            await self.bot.db.execute(
                """
                INSERT INTO reaction_history
                    (guild_id, channel_id, message_id, reaction, user_id, ts)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (guild_id, channel_id, message_id, reaction, user_id)
                DO UPDATE SET ts = EXCLUDED.ts
                """,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
                str(payload.emoji),
                payload.user_id,
                datetime.datetime.utcnow(),
            )
        except Exception:
            return False
        return True

    async def get_entry(
        self,
        channel: discord.abc.GuildChannel | discord.Thread | discord.TextChannel,
        *,
        type: str = "snipe",
        index: int = 1,
    ) -> tuple:
        """Get snipe entry at *index* (1-based) for *channel*."""
        prefix = self._prefix(type)
        label = {
            "snipe": "deleted messages",
            "editsnipe": "edits",
            "reactionsnipe": "reaction removals",
        }.get((type or "snipe").lower(), "entries")
        data = self.data.get(self._key(prefix, channel.id))
        if not data:
            raise SnipeError(f"no {label} in {getattr(channel, 'mention', channel.id)}")
        if index < 1 or len(data) < index:
            raise SnipeError(f"not {index} {label} stored")
        return (data[index - 1], len(data))

    async def delete_entry(
        self,
        channel: discord.abc.GuildChannel | discord.Thread | discord.TextChannel,
        kind: str,
        index: int,
    ) -> None:
        prefix = self._prefix(kind)
        key = self._key(prefix, channel.id)
        data = self.data.get(key)
        if not data or index < 1 or len(data) < index:
            raise SnipeError(f"no entry at {index}")
        del data[index - 1]

    async def clear_entries(
        self,
        channel: discord.abc.GuildChannel | discord.Thread | discord.TextChannel,
    ) -> None:
        for prefix in ("s-", "es-", "rs-"):
            self.data.pop(self._key(prefix, channel.id), None)
