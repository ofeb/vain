from discord.ext.commands import Cog
from .notes import Notes


class Notes(Notes, Cog):
    """notes cog"""


async def setup(bot):
    """load notes cog"""
    await bot.add_cog(Notes(bot))
