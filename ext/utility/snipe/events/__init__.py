from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core.vain import Vain


class SnipeEvents(commands.Cog):
    """Capture deletes, edits, and reaction removals for sniping."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener("on_raw_message_delete")
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        message = payload.cached_message
        if message is None:
            return
        if message.guild is None:
            return
        if message.author.bot:
            return
        
        if not (
            message.content
            or message.attachments
            or message.stickers
            or any(e.type not in ("image", "video") for e in message.embeds)
        ):
            return
        await self.bot.snipes.add_entry("snipe", message)

    @commands.Cog.listener("on_raw_bulk_message_delete")
    async def on_raw_bulk_message_delete(
        self, payload: discord.RawBulkMessageDeleteEvent
    ) -> None:
        for message in payload.cached_messages or []:
            if message.guild is None or message.author.bot:
                continue
            if not (
                message.content
                or message.attachments
                or message.stickers
                or message.embeds
            ):
                continue
            await self.bot.snipes.add_entry("snipe", message)

    @commands.Cog.listener("on_raw_message_edit")
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        
        before = payload.cached_message
        if before is None:
            return
        if before.guild is None or before.author.bot:
            return

        data = payload.data or {}
        after_content = data.get("content")
        if after_content is None:
            return
        if before.content == after_content:
            return
        
        await self.bot.snipes.add_entry("editsnipe", before)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if not payload.guild_id:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        
        try:
            await self.bot.snipes.add_reaction_history(payload)
        except Exception:
            pass

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id) or self.bot.get_channel(
            payload.channel_id
        )
        if channel is None:
            return

        user = guild.get_member(payload.user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(payload.user_id)
            except Exception:
                return
        if getattr(user, "bot", False):
            return

        
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            
            class _Msg:
                channel = channel
                jump_url = (
                    f"https://discord.com/channels/{payload.guild_id}/"
                    f"{payload.channel_id}/{payload.message_id}"
                )

            message = _Msg()

        emoji = payload.emoji
        reaction = str(emoji)
        if emoji.is_custom_emoji() and emoji.id:
            
            ext = "gif" if emoji.animated else "png"
            reaction = f"https://cdn.discordapp.com/emojis/{emoji.id}.{ext}"

        await self.bot.snipes.add_entry(
            "reactionsnipe", (message, reaction, user)
        )


async def setup(bot: commands.Bot) -> None:
    
    if bot.get_cog("SnipeEvents") is None:
        await bot.add_cog(SnipeEvents(bot))
