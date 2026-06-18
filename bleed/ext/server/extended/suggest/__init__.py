from __future__ import annotations

from discord.ext.commands import Cog

from .suggest import SuggestCommands


class Suggest(SuggestCommands, Cog):
    """suggestion channel cog"""


async def setup(bot) -> None:
    """load suggest cog"""
    await bot.add_cog(Suggest(bot))
