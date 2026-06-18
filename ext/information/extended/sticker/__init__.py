from discord.ext.commands import Cog
from .sticker import Sticker


class Sticker(Sticker, Cog):
    """sticker cog"""


async def setup(bot):
    """load sticker cog"""
    await bot.add_cog(Sticker(bot))
