from discord.ext.commands import Cog
from .welcome import WelcomeCommands


class Welcome(WelcomeCommands, Cog):
    """welcome cog"""

    @Cog.listener("on_member_agree")
    async def _on_join(self, member):
        """proxy join event"""
        await self.on_member_agree(member)


async def setup(bot):
    """load welcome cog"""
    await bot.add_cog(Welcome(bot))
