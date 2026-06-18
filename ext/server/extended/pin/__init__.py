from discord.ext.commands import Cog
from .pin import PinCommands


class Pin(PinCommands, Cog):
    """pin cog"""


async def setup(bot):
    """load pin cog"""
    await bot.add_cog(Pin(bot))
