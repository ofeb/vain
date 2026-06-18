from discord.ext.commands import Cog
from .goodbye import GoodbyeCommands


class Goodbye(GoodbyeCommands, Cog):
    """goodbye cog"""

    @Cog.listener("on_member_remove")
    async def _on_leave(self, member):
        """proxy leave event"""
        await self.on_member_remove(member)


async def setup(bot):
    """load goodbye cog"""
    await bot.add_cog(Goodbye(bot))
