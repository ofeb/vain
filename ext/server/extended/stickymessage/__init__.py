from discord.ext.commands import Cog
from .stickymessage import StickymessageCommands


class Stickymessage(StickymessageCommands, Cog):
    """stickymessage cog"""


async def setup(bot):
    """load stickymessage cog"""
    await bot.add_cog(Stickymessage(bot))
