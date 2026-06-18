from discord.ext.commands import Cog
from .timeout import Timeout


class Timeout(Timeout, Cog):
    """timeout cog"""


async def setup(bot):
    """load timeout cog"""
    await bot.add_cog(Timeout(bot))
