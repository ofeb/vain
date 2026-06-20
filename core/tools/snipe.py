"""in memory snipe message store.
keeps last 100 deleted edited and reaction removed per channel.
use add_entry then get_entry to retrieve"""

import asyncio
import datetime
import typing
from collections import deque
import discord


class SnipeError(Exception):
    """no snipe entry found"""
    pass


class Snipe:
    """stores recent deleted edited and reaction removed messages.
    indexed per channel with deque of max 100 entries.
    type is snipe editsnipe or reactionsnipe"""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.data: dict = {}

    def _key(self, prefix: str, channel_id: int) -> str:
        return f"{prefix}{channel_id}"

    def _store(self, key: str, entry: dict) -> None:
        if key not in self.data:
            self.data[key] = deque(maxlen=100)
        self.data[key].appendleft(entry)

    async def add_entry(self, kind: str, message: typing.Union[discord.Message, tuple]) -> dict:
        """store a snipe entry for a channel"""
        if isinstance(message, discord.Message):
            entry = {
                "timestamp": message.created_at.timestamp(),
                "content": message.content,
                "embeds": [
                    e.to_dict() for e in message.embeds[:8]
                    if e.type not in ("image", "video")
                ],
                "attachments": [
                    a.proxy_url for a in message.attachments
                ] + [
                    (e.thumbnail or e.image).url
                    for e in message.embeds if e.type == "image"
                    and (e.thumbnail or e.image)
                ],
                "stickers": [s.url for s in message.stickers],
                "author": {
                    "id": message.author.id,
                    "name": message.author.name,
                    "avatar": message.author.display_avatar.url,
                },
            }
            prefix = {"snipe": "s-", "editsnipe": "es-"}.get(kind.lower(), "s-")
            self._store(self._key(prefix, message.channel.id), entry)
        else:
            msg, reaction, user = message
            entry = {
                "timestamp": datetime.datetime.now().timestamp(),
                "message": msg.jump_url,
                "reaction": str(reaction),
                "author": {
                    "id": user.id,
                    "name": user.name,
                    "avatar": user.display_avatar.url,
                },
            }
            self._store(self._key("rs-", msg.channel.id), entry)
        return entry

    async def add_reaction_history(self, payload: discord.RawReactionActionEvent) -> bool:
        """log reaction removal to database"""
        if payload.user_id == self.bot.user.id:
            return False
        await self.bot.db.execute(
            """INSERT INTO reaction_history (guild_id, channel_id, message_id, reaction, user_id, ts)
               VALUES($1,$2,$3,$4,$5,$6)
               ON CONFLICT(guild_id,channel_id,message_id,reaction,user_id) DO UPDATE SET ts = excluded.ts""",
            payload.guild_id, payload.channel_id, payload.message_id,
            str(payload.emoji), payload.user_id, datetime.datetime.now(),
        )
        return True

    async def get_entry(self, channel: discord.TextChannel, *, type: str = "snipe", index: int = 1) -> tuple:
        """get snipe entry at index for channel"""
        prefix = {"snipe": "s-", "editsnipe": "es-", "reactionsnipe": "rs-"}.get(type.lower(), "s-")
        label = {"snipe": "deleted messages", "editsnipe": "edits", "reactionsnipe": "reaction removals"}.get(type.lower(), "entries")
        data = self.data.get(self._key(prefix, channel.id))
        if not data:
            raise SnipeError(f"no {label} in {channel.mention}")
        if len(data) < index:
            raise SnipeError(f"not {index} {label} stored")
        return (data[index - 1], len(data))

    async def delete_entry(self, channel: discord.TextChannel, kind: str, index: int) -> None:
        """remove a snipe entry at index"""
        prefix = {"snipe": "s-", "editsnipe": "es-", "reactionsnipe": "rs-"}.get(kind.lower(), "s-")
        key = self._key(prefix, channel.id)
        data = self.data.get(key)
        if not data or len(data) < index:
            raise SnipeError(f"no entry at {index}")
        self.data[key].remove(data[index - 1])

    async def clear_entries(self, channel: discord.TextChannel) -> None:
        """clear all snipe data for a channel"""
        for prefix in ("s-", "es-", "rs-"):
            self.data.pop(self._key(prefix, channel.id), None)
