from discord.ext.commands import Cog
from .customize import CustomizeCommands


class Customize(CustomizeCommands, Cog):
    """customize cog"""


async def setup(bot):
    """load customize cog"""
    await bot.add_cog(Customize(bot))
