from discord.ext.commands import Cog
from .emoji import Emoji


class Emoji(Emoji, Cog):
    """emoji cog"""


async def setup(bot):
    """load emoji cog"""
    await bot.add_cog(Emoji(bot))
