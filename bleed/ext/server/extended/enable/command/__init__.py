from discord.ext.commands import Cog
from .command import CommandEnableCommands


class Command(CommandEnableCommands, Cog):
    """enable command cog"""


async def setup(bot):
    """load enable command cog"""
    await bot.add_cog(Command(bot))
