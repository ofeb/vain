from discord.ext.commands import Cog
from .pagination import PaginationCommands


class Pagination(PaginationCommands, Cog):
    """pagination cog"""


async def setup(bot):
    """load pagination cog"""
    await bot.add_cog(Pagination(bot))
