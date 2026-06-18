from discord.ext.commands import Cog
from .restrictcommand import Restrictcommand


class Restrictcommand(Restrictcommand, Cog):
    """restrictcommand cog"""


async def setup(bot):
    """load restrictcommand cog"""
    await bot.add_cog(Restrictcommand(bot))
