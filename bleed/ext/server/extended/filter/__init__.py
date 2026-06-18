from discord.ext.commands import Cog
from .filter import FilterCommands


class Filter(FilterCommands, Cog):
    """filter cog"""


async def setup(bot):
    """load filter cog"""
    await bot.add_cog(Filter(bot))
