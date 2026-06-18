from discord.ext.commands import Cog
from .remind import Remind


class Remind(Remind, Cog):
    """remind cog"""


async def setup(bot):
    """load remind cog"""
    await bot.add_cog(Remind(bot))
