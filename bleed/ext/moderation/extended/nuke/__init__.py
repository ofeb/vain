from discord.ext.commands import Cog
from .nuke import Nuke


class Nuke(Nuke, Cog):
    """nuke cog"""


async def setup(bot):
    """load nuke cog"""
    await bot.add_cog(Nuke(bot))
