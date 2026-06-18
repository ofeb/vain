from discord.ext.commands import Cog
from .revokefiles import Revokefiles


class Revokefiles(Revokefiles, Cog):
    """revokefiles cog"""


async def setup(bot):
    """load revokefiles cog"""
    await bot.add_cog(Revokefiles(bot))
