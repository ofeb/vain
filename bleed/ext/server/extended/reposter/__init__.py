from __future__ import annotations

from discord.ext.commands import Cog

from .reposter import ReposterCommands


class Reposter(ReposterCommands, Cog):
    """media repost cog"""


async def setup(bot) -> None:
    """load reposter cog"""
    await bot.add_cog(Reposter(bot))
