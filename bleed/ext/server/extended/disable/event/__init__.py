from discord.ext.commands import Cog
from .event import EventDisableCommands


class Event(EventDisableCommands, Cog):
    """disable event cog"""


async def setup(bot):
    """load disable event cog"""
    await bot.add_cog(Event(bot))
