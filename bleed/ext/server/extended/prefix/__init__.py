from discord.ext.commands import Cog
from .prefix import PrefixCommands


class Prefix(PrefixCommands, Cog):
    """prefix management cog"""


async def setup(bot):
    """load prefix cog"""
    await bot.add_cog(Prefix(bot))
