from discord.ext.commands import Cog
from .goodbye import GoodbyeCommands


class Goodbye(GoodbyeCommands, Cog):
    """goodbye cog"""


async def setup(bot):
    """load goodbye cog"""
    await bot.add_cog(Goodbye(bot))
