from discord.ext.commands import Cog
from .alias import AliasCommands


class Alias(AliasCommands, Cog):
    """alias cog"""


async def setup(bot):
    """load alias cog"""
    await bot.add_cog(Alias(bot))
