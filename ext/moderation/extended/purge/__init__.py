from discord.ext.commands import Cog
from .purge import Purge


class Purge(Purge, Cog):
    """purge cog"""


async def setup(bot):
    """load purge cog"""
    await bot.add_cog(Purge(bot))
