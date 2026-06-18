from discord.ext.commands import Cog
from .settings import SettingsCommands


class Settings(SettingsCommands, Cog):
    """settings cog"""

    @Cog.listener("on_vanity_change")
    async def _on_vanity(self, vanity):
        """proxy vanity event"""
        await self.on_vanity_change(vanity)

    @Cog.listener("on_username_change")
    async def _on_username(self, username):
        """proxy username event"""
        await self.on_username_change(username)


async def setup(bot):
    """load settings cog"""
    await bot.add_cog(Settings(bot))
