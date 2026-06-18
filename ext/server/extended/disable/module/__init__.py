from discord.ext.commands import Cog
from .module import ModuleDisableCommands


class Module(ModuleDisableCommands, Cog):
    """disable module cog"""


async def setup(bot):
    """load disable module cog"""
    await bot.add_cog(Module(bot))
