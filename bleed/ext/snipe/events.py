from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from .snipe import Snipe


class SnipeEvents(commands.Cog):
    """Snipe event handlers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener("on_raw_reaction_remove")
    async def on_reaction_history(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle reaction history logging."""
        await self.bot.snipes.add_reaction_history(payload)

    @commands.Cog.listener("on_message_delete")
    async def on_snipe_entry(self, message: discord.Message) -> None:
        """Handle message deletion sniping."""
        if message.author.id == self.bot.user.id:
            return
        await self.bot.snipes.add_entry("snipe", message)

    @commands.Cog.listener("on_message_edit")
    async def on_edit_snipe(self, before: discord.Message, after: discord.Message) -> None:
        """Handle message edit sniping."""
        if before.content != after.content and before.author.id != self.bot.user.id:
            await self.bot.snipes.add_entry("editsnipe", before)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def on_reaction_snipe(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle reaction removal sniping."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        if not payload.member:
            payload.member = guild.get_member(payload.user_id) or await self.bot.fetch_user(payload.user_id)
        
        message = await channel.fetch_message(payload.message_id)
        await self.bot.snipes.add_entry("rs", (message, payload.emoji, payload.member))


async def setup(bot: commands.Bot):
    """Load the SnipeEvents cog."""
    await bot.add_cog(SnipeEvents(bot))
