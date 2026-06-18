from discord.ext.commands import Cog
from .imgonly import ImgonlyCommands


class Imgonly(ImgonlyCommands, Cog):
    """imgonly cog"""


async def setup(bot):
    """load imgonly cog"""
    await bot.add_cog(Imgonly(bot))
