from discord.ext.commands import Cog
from .autoresponder import AutoresponderCommands


class Autoresponder(AutoresponderCommands, Cog):
    """autoresponder cog"""


async def setup(bot):
    """load autoresponder cog"""
    await bot.add_cog(Autoresponder(bot))
