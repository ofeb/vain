from discord.ext.commands import Cog
from .welcome import WelcomeCommands


class Welcome(WelcomeCommands, Cog):
    """welcome cog"""


async def setup(bot):
    """load welcome cog"""
    await bot.add_cog(Welcome(bot))
