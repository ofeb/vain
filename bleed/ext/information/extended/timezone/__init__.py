from discord.ext.commands import Cog
from .timezone import Timezone


class Timezone(Timezone, Cog):
    """timezone cog"""


async def setup(bot):
    """load timezone cog"""
    await bot.add_cog(Timezone(bot))
