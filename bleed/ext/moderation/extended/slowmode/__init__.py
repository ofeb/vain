from discord.ext.commands import Cog
from .slowmode import Slowmode


class Slowmode(Slowmode, Cog):
    """slowmode cog"""


async def setup(bot):
    """load slowmode cog"""
    await bot.add_cog(Slowmode(bot))
