from discord.ext.commands import Cog
from .set import SetCommands


class Set(SetCommands, Cog):
    """set cog"""


async def setup(bot):
    """load set cog"""
    await bot.add_cog(Set(bot))
