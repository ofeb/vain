from discord.ext.commands import Cog
from .boosterrole import BoosterroleCommands


class Boosterrole(BoosterroleCommands, Cog):
    """boosterrole cog"""


async def setup(bot):
    """load boosterrole cog"""
    await bot.add_cog(Boosterrole(bot))
