from discord.ext.commands import Cog
from .stickyrole import Stickyrole


class Stickyrole(Stickyrole, Cog):
    """stickyrole cog"""


async def setup(bot):
    """load stickyrole cog"""
    await bot.add_cog(Stickyrole(bot))
