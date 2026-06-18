from discord.ext.commands import Cog
from .forcenickname import Forcenickname


class Forcenickname(Forcenickname, Cog):
    """forcenickname cog"""


async def setup(bot):
    """load forcenickname cog"""
    await bot.add_cog(Forcenickname(bot))
