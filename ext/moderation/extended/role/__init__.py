from discord.ext.commands import Cog
from .role import Role


class Role(Role, Cog):
    """role cog"""


async def setup(bot):
    """load role cog"""
    await bot.add_cog(Role(bot))
