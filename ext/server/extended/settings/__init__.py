from discord.ext.commands import Cog
from .settings import SettingsCommands


class Settings(SettingsCommands, Cog):
    """settings cog"""


async def setup(bot):
    """load settings cog"""
    await bot.add_cog(Settings(bot))
