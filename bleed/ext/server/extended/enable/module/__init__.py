from discord.ext.commands import Cog
from .module import ModuleEnableCommands


class Module(ModuleEnableCommands, Cog):
    """enable module cog"""


async def setup(bot):
    """load enable module cog"""
    await bot.add_cog(Module(bot))
