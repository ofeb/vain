from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context

if TYPE_CHECKING:
    from ..reaction import Reaction


class ReactionEvents(commands.Cog):
    """Auto-reaction event handlers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener("on_valid_message")
    async def on_auto_reaction(self, ctx: Context) -> None:
        """Handle auto-reactions on valid messages."""
        words = [r.lower() for r in ctx.message.content.split(" ")]
        words.append(str(ctx.channel.id))
        records = await self.bot.db.fetch(
            "SELECT * FROM auto_reactions WHERE guild_id = $1 AND trigger = ANY($2)",
            ctx.guild.id,
            words,
        )
        for record in records:
            for reaction in record.response:
                await ctx.message.add_reaction(str(reaction))


async def setup(bot: commands.Bot):
    """Load the ReactionEvents cog."""
    await bot.add_cog(ReactionEvents(bot))
