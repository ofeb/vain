from discord.ext.commands import Cog
from .ignore import IgnoreCommands


class Ignore(IgnoreCommands, Cog):
    """ignore cog"""


async def setup(bot):
    """load ignore cog"""
    await bot.add_cog(Ignore(bot))
