from discord.ext.commands import Cog
from .command import CommandDisableCommands


class Command(CommandDisableCommands, Cog):
    """disable command cog"""


async def setup(bot):
    """load disable command cog"""
    await bot.add_cog(Command(bot))
