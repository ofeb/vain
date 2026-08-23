from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core.vain import Vain

from ..settings import Config


class StarboardEvents(commands.Cog):
    """Reaction listeners for multi-emoji starboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    async def cog_load(self) -> None:
        await Config.ensure_schema(self.bot)  # type: ignore[arg-type]

    async def _get_config(
        self, guild: discord.Guild, emoji: str
    ) -> Config | None:
        return await Config.fetch_emoji(self.bot, guild, str(emoji))  # type: ignore[arg-type]

    async def _reaction_action(
        self, fmt: str, payload: discord.RawReactionActionEvent
    ) -> None:
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None or (guild.me and getattr(guild.me, "is_timed_out", lambda: False)()):
            return

        channel = guild.get_channel_or_thread(payload.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        starboard = await self._get_config(guild, str(payload.emoji))
        if (
            starboard is None
            or starboard.channel is None
            or starboard.channel.id == channel.id
            or starboard.lock
        ):
            return

        board = starboard.channel
        me = guild.me
        if me is None:
            return
        perms = board.permissions_for(me)
        if not (perms.send_messages and perms.embed_links):
            return

        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        
        if starboard.ignore_entries:
            raw = starboard.ignore_entries
            try:
                ignored = set(json.loads(raw) if isinstance(raw, str) else (raw or []))
            except Exception:
                ignored = set()
            snowflakes = {member.id, channel.id, *(r.id for r in member.roles)}
            if ignored & snowflakes:
                return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        async with self._lock_for(guild.id):
            if fmt == "star":
                await self._star(starboard, channel=channel, member=member, message=message)
            else:
                await self._unstar(starboard, channel=channel, member=member, message=message)

    async def _star(
        self,
        starboard: Config,
        *,
        channel: discord.TextChannel | discord.Thread,
        member: discord.Member,
        message: discord.Message,
    ) -> None:
        board = starboard.channel
        if board is None:
            return
        if getattr(channel, "is_nsfw", lambda: False)() and not getattr(
            board, "is_nsfw", lambda: False
        )():
            return
        if message.author.id == member.id and not starboard.self_star:
            return

        reaction = discord.utils.find(
            lambda r: str(r.emoji) == starboard.emoji, message.reactions
        )
        if reaction is None or reaction.count < starboard.threshold:
            return

        view = self._render(starboard, reaction, message)
        await starboard.save_star(stars=reaction.count, message=message, view=view)

    async def _unstar(
        self,
        starboard: Config,
        *,
        channel: discord.TextChannel | discord.Thread,
        member: discord.Member,
        message: discord.Message,
    ) -> None:
        reaction = discord.utils.find(
            lambda r: str(r.emoji) == starboard.emoji, message.reactions
        )
        if reaction is None or reaction.count < starboard.threshold:
            await starboard.delete_star(
                message_id=message.id, channel_id=channel.id
            )
            return
        view = self._render(starboard, reaction, message)
        await starboard.save_star(
            stars=reaction.count, message=message, view=view
        )

    @staticmethod
    def _glyph(starboard: Config, count: int) -> str:
        emoji = starboard.emoji
        if emoji != "⭐":
            return emoji
        if count < 5:
            return "⭐"
        if count < 10:
            return "🌟"
        if count < 25:
            return "💫"
        return "✨"

    def _render(
        self,
        starboard: Config,
        reaction: discord.Reaction,
        message: discord.Message,
    ):
        glyph = self._glyph(starboard, reaction.count)

        container = discord.ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)

        container.add_item(
            discord.ui.TextDisplay(
                f"{glyph} **{reaction.count:,}** · <#{message.channel.id}>"
            )
        )
        container.add_item(
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )

        subtitle = (
            f"-# <t:{int(message.created_at.timestamp())}:R>"
            if starboard.ts
            else ""
        )
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"**{message.author.display_name}**\n{subtitle}".rstrip()
                ),
                accessory=discord.ui.Thumbnail(
                    media=message.author.display_avatar.url
                ),
            )
        )

        lines: list[str] = []
        if message.content:
            lines.append(message.content[:2000])

        media_url = None
        if starboard.attachments:
            for att in message.attachments:
                url = att.url.lower()
                if url.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    media_url = att.url
                    break
            if media_url is None and message.embeds:
                embedded = message.embeds[0]
                if embedded.image and embedded.image.url:
                    media_url = embedded.image.url
                elif embedded.thumbnail and embedded.thumbnail.url:
                    media_url = embedded.thumbnail.url

        if lines:
            container.add_item(discord.ui.TextDisplay("\n".join(lines)))
        elif media_url is None:
            container.add_item(discord.ui.TextDisplay("*no content*"))

        if media_url:
            with contextlib.suppress(Exception):
                container.add_item(
                    discord.ui.MediaGallery(
                        discord.MediaGalleryItem(media_url)
                    )
                )

        if starboard.jump:
            footer = f"-# [jump to message]({message.jump_url})"
            if getattr(message.channel, "name", None):
                footer += f" · #{message.channel.name}"
            container.add_item(discord.ui.TextDisplay(footer))

        from core.discord.ctx import layout_from_items

        return layout_from_items([container], timeout=None)

    @commands.Cog.listener("on_raw_reaction_add")
    async def starboard_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._reaction_action("star", payload)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def starboard_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._reaction_action("unstar", payload)

    @commands.Cog.listener("on_guild_channel_delete")
    async def starboard_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        await self.bot.db.execute(
            "DELETE FROM starboard WHERE guild_id = $1 AND channel_id = $2",
            channel.guild.id,
            channel.id,
        )
        for table in ("starboard_entry", "starboard_entries"):
            with contextlib.suppress(Exception):
                await self.bot.db.execute(
                    f"DELETE FROM {table} WHERE guild_id = $1 AND channel_id = $2",
                    channel.guild.id,
                    channel.id,
                )

    @commands.Cog.listener("on_raw_reaction_clear")
    async def starboard_reaction_clear(
        self, payload: discord.RawReactionClearEmojiEvent
    ) -> None:
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        for table, col in (
            ("starboard_entry", "star_id"),
            ("starboard_entries", "starboard_message_id"),
        ):
            try:
                rows = await self.bot.db.fetch(
                    f"""
                    DELETE FROM {table}
                    WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
                    RETURNING {col} AS star_id, emoji
                    """,
                    payload.guild_id,
                    payload.channel_id,
                    payload.message_id,
                )
            except Exception:
                continue
            for row in rows or []:
                cfg = await self._get_config(guild, row["emoji"])
                if cfg and cfg.channel:
                    with contextlib.suppress(Exception):
                        await cfg.channel.get_partial_message(int(row["star_id"])).delete()
