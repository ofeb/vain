from discord.ext.commands import Cog
from .badge import BadgeCommands


class Badge(BadgeCommands, Cog):
    """badge cog"""


async def setup(bot):
    """load badge cog"""
    await bot.add_cog(Badge(bot))
