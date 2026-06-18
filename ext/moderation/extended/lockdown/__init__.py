from discord.ext.commands import Cog
from .lockdown import Lockdown


class Lockdown(Lockdown, Cog):
    """lockdown cog"""


async def setup(bot):
    """load lockdown cog"""
    await bot.add_cog(Lockdown(bot))
