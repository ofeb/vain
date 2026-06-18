from discord.ext.commands import Cog
from .roblox import Roblox


class Roblox(Roblox, Cog):
    """roblox cog"""


async def setup(bot):
    """load roblox cog"""
    await bot.add_cog(Roblox(bot))
