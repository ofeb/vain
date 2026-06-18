from discord.ext.commands import Cog
from .event import EventEnableCommands


class Event(EventEnableCommands, Cog):
    """enable event cog"""


async def setup(bot):
    """load enable event cog"""
    await bot.add_cog(Event(bot))
