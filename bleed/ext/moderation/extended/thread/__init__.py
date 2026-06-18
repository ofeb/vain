from discord.ext.commands import Cog
from .thread import Thread


class Thread(Thread, Cog):
    """thread cog"""


async def setup(bot):
    """load thread cog"""
    await bot.add_cog(Thread(bot))
