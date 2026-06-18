from discord.ext.commands import Cog
from .birthday import Birthday


class Birthday(Birthday, Cog):
    """birthday cog"""


async def setup(bot):
    """load birthday cog"""
    await bot.add_cog(Birthday(bot))
