from discord.ext.commands import Cog
from .snapchat import Snapchat


class Snapchat(Snapchat, Cog):
    """snapchat cog"""


async def setup(bot):
    """load snapchat cog"""
    await bot.add_cog(Snapchat(bot))
