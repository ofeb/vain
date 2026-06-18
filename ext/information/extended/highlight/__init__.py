from discord.ext.commands import Cog
from .highlight import Highlight


class Highlight(Highlight, Cog):
    """highlight cog"""


async def setup(bot):
    """load highlight cog"""
    await bot.add_cog(Highlight(bot))
