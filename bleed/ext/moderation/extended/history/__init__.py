from discord.ext.commands import Cog
from .history import History


class History(History, Cog):
    """history cog"""


async def setup(bot):
    """load history cog"""
    await bot.add_cog(History(bot))
