from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

import discord
from discord.ext import commands

from config import color



def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def panel_embed(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description or None, url=url)
    if title:
        embed.title = title
    if author:
        if author_icon:
            embed.set_author(name=author, icon_url=author_icon)
        else:
            embed.set_author(name=author)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed



if TYPE_CHECKING:
    from .. import Clownboard

_TENOR_GIF = re.compile(
    r"(?i)\b((https?://c[.]tenor[.]com/)"
    r"(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))[.]gif)"
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_MEDIA_SUFFIXES = (".mp4", ".mov", ".webm", "mp3", ".ogg", ".wav")


class ClownboardEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()
        self._about_to_be_deleted: set[int] = set()

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            self._locks[guild_id] = lock = asyncio.Lock()
        return lock

    async def _dispatch(
        self, action: str, payload: discord.RawReactionActionEvent
    ) -> None:
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        config = await self.bot.db.fetchrow(
            "SELECT * FROM clownboard WHERE guild_id = $1", guild.id
        )
        if config is None:
            return
        if str(config["emoji"]) != str(payload.emoji):
            return

        board = guild.get_channel(config["channel_id"])
        if board is None:
            return
        if not board.permissions_for(guild.me).send_messages:
            return

        member = payload.member or guild.get_member(payload.user_id)
        if member is None:
            return

        if config["ignore_entries"]:
            ignored = set(json.loads(config["ignore_entries"]))
            snowflakes = {member.id, channel.id, *(r.id for r in member.roles)}
            if ignored & snowflakes:
                return
        if config["lock"]:
            return

        handler = self._clown if action == "clown" else self._unclown
        with contextlib.suppress(Exception):
            await handler(config, board, guild, channel, member, payload.message_id)

    @commands.Cog.listener("on_raw_reaction_add")
    async def clownboard_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._dispatch("clown", payload)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def clownboard_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._dispatch("unclown", payload)

    @commands.Cog.listener("on_guild_channel_delete")
    async def clownboard_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        await self.bot.db.execute(
            "DELETE FROM clownboard WHERE guild_id = $1 AND channel_id = $2",
            channel.guild.id,
            channel.id,
        )

    @commands.Cog.listener("on_raw_reaction_clear")
    async def clownboard_reaction_clear(
        self, payload: discord.RawReactionClearEmojiEvent
    ) -> None:
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        entry = await self.bot.db.fetchrow(
            "DELETE FROM clownboard_entries WHERE message_id = $1 "
            "RETURNING emoji, clownboard_message_id",
            payload.message_id,
        )
        if entry is None:
            return

        board_row = await self.bot.db.fetchrow(
            "SELECT channel_id FROM clownboard WHERE guild_id = $1 AND emoji = $2",
            guild.id,
            entry["emoji"],
        )
        if board_row is None:
            return
        board = guild.get_channel(board_row["channel_id"])
        if board is None:
            return
        with contextlib.suppress(discord.HTTPException):
            await board.delete_messages(
                [discord.Object(id=entry["clownboard_message_id"])]
            )

    @commands.Cog.listener("on_raw_message_delete")
    async def clownboard_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        if payload.message_id in self._about_to_be_deleted:
            self._about_to_be_deleted.discard(payload.message_id)
            return
        await self.bot.db.execute(
            "DELETE FROM clownboard_entries WHERE guild_id = $1 "
            "AND clownboard_message_id = $2",
            payload.guild_id,
            payload.message_id,
        )

    @commands.Cog.listener("on_raw_bulk_message_delete")
    async def clownboard_bulk_message_delete(
        self, payload: discord.RawBulkMessageDeleteEvent
    ) -> None:
        if payload.message_ids <= self._about_to_be_deleted:
            self._about_to_be_deleted.difference_update(payload.message_ids)
            return
        await self.bot.db.execute(
            "DELETE FROM clownboard_entries WHERE guild_id = $1 "
            "AND clownboard_message_id = ANY($2::BIGINT[])",
            payload.guild_id,
            list(payload.message_ids),
        )

    async def _eligible(
        self,
        config: dict,
        board: discord.TextChannel,
        channel: discord.TextChannel,
        member: discord.Member,
        message: discord.Message,
    ) -> bool:
        if channel.is_nsfw() and not board.is_nsfw():
            return False
        if message.author.id == self.bot.user.id:
            return False
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return False
        if message.author.id == member.id and not config.get("self_star", True):
            return False
        if (not message.content and not message.attachments) or message.type not in (
            discord.MessageType.default,
            discord.MessageType.reply,
        ):
            return False
        return True

    @staticmethod
    def _trigger(message: discord.Message, emoji: str) -> discord.Reaction | None:
        for reaction in message.reactions:
            if str(reaction.emoji) == emoji:
                return reaction
        return None

    async def _clown(
        self,
        config: dict,
        board: discord.TextChannel,
        guild: discord.Guild,
        channel: discord.TextChannel,
        member: discord.Member,
        message_id: int,
    ) -> None:
        async with self._lock_for(guild.id):
            message = await channel.fetch_message(message_id)
            if message is None or not await self._eligible(
                config, board, channel, member, message
            ):
                return

            reaction = self._trigger(message, config["emoji"])
            if reaction is None:
                return
            count = len(
                [user async for user in reaction.users() if user != self.bot.user]
            )
            if count < config["threshold"]:
                return

            existing = await self.bot.db.fetchval(
                "SELECT clownboard_message_id FROM clownboard_entries WHERE "
                "guild_id = $1 AND channel_id = $2 AND message_id = $3 AND emoji = $4",
                guild.id,
                channel.id,
                message.id,
                config["emoji"],
            )
            content, embed, files = await self._render(config, reaction, message)

            if existing:
                with contextlib.suppress(discord.HTTPException):
                    await board.get_partial_message(existing).edit(content=content)
                    return

            try:
                posted = await board.send(content=content, embed=embed, files=files)
            except discord.HTTPException:
                return
            await self.bot.db.execute(
                "INSERT INTO clownboard_entries (guild_id, channel_id, message_id, "
                "emoji, clownboard_message_id) VALUES ($1, $2, $3, $4, $5)",
                guild.id,
                channel.id,
                message.id,
                config["emoji"],
                posted.id,
            )

    async def _unclown(
        self,
        config: dict,
        board: discord.TextChannel,
        guild: discord.Guild,
        channel: discord.TextChannel,
        member: discord.Member,
        message_id: int,
    ) -> None:
        async with self._lock_for(guild.id):
            existing = await self.bot.db.fetchval(
                "SELECT clownboard_message_id FROM clownboard_entries WHERE "
                "guild_id = $1 AND channel_id = $2 AND message_id = $3 AND emoji = $4",
                guild.id,
                channel.id,
                message_id,
                config["emoji"],
            )
            if not existing:
                return

            message = await channel.fetch_message(message_id)
            if message is None or message.author.id == self.bot.user.id:
                return
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return

            reaction = self._trigger(message, config["emoji"])
            if reaction is None:
                with contextlib.suppress(discord.HTTPException):
                    await board.delete_messages([discord.Object(id=existing)])
                await self.bot.db.execute(
                    "DELETE FROM clownboard_entries WHERE clownboard_message_id = $1",
                    existing,
                )
                return

            content, _embed, _files = await self._render(config, reaction, message)
            try:
                await board.get_partial_message(existing).edit(content=content)
            except discord.HTTPException:
                await self.bot.db.execute(
                    "DELETE FROM clownboard_entries WHERE clownboard_message_id = $1",
                    existing,
                )

    async def _render(
        self, config: dict, reaction: discord.Reaction, message: discord.Message
    ) -> tuple[str, discord.Embed, list[discord.File] | None]:
        files: list[discord.File] | None = None

        source_embed = message.embeds[0] if message.embeds else None
        if source_embed is not None and source_embed.type not in (
            "image",
            "gif",
            "gifv",
        ):
            embed = source_embed
        else:
            embed_color = (
                int(config["color"], 16)
                if config.get("color")
                else message.author.color.value
            )
            embed = panel_embed(color=embed_color, lines=[], timestamp=False)

        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar,
        )
        if config.get("jump"):
            embed.author.url = message.jump_url
        if config.get("ts"):
            embed.timestamp = message.created_at

        body = message.content[:2048] if message.content else ""
        existing = embed.description[:2048] if embed.description else ""
        embed.description = f"{body}\n{existing}"

        if config.get("attachments"):
            await self._attach_media(embed, message)
            files = []
            for attachment in message.attachments:
                lowered = attachment.url.lower()
                if lowered.endswith(_IMAGE_SUFFIXES):
                    embed.set_image(url=attachment.url)
                elif lowered.endswith(_MEDIA_SUFFIXES):
                    embed.set_image(url=attachment.url)
                    downloaded = await attachment.to_file()
                    if (
                        not sys.getsizeof(downloaded.fp)
                        > message.guild.filesize_limit
                    ):
                        files.append(downloaded)

        if message.reference and (reference := message.reference.resolved):
            embed.add_field(
                name=f"**Replying to {reference.author.display_name}**",
                value=f"[Jump to reply]({reference.jump_url})",
                inline=False,
            )
        if config.get("jump"):
            embed.add_field(
                name=f"**#{message.channel}**",
                value=f"[Jump to message]({message.jump_url})",
                inline=False,
            )
        if config.get("ts"):
            embed.timestamp = message.created_at

        reactions = f"#{reaction.count:,}"
        if str(reaction.emoji) == "⭐":
            if reaction.count < 5:
                glyph = "⭐"
            elif reaction.count < 10:
                glyph = "🌟"
            elif reaction.count < 25:
                glyph = "💫"
            else:
                glyph = "✨"
        else:
            glyph = str(reaction.emoji)
        return f"{glyph} **{reactions}**", embed, files

    async def _attach_media(
        self, embed: discord.Embed, message: discord.Message
    ) -> None:
        if not message.embeds:
            return
        media = message.embeds[0]
        if not (media.url and media.type in ("image", "gifv")):
            return
        embed.description = embed.description.replace(media.url, "")
        if media.type == "image":
            embed.set_image(url=media.url)
            return
        try:
            async with self.bot.http.get(media.url) as response:
                data = await response.text()
        except Exception:
            if media.thumbnail and media.thumbnail.url:
                embed.set_image(url=media.thumbnail.url)
            return
        match = _TENOR_GIF.search(data)
        if match:
            embed.set_image(url=match.group(1))
