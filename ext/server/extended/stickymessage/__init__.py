from discord.ext.commands import Cog
from .stickymessage import StickymessageCommands


class Stickymessage(StickymessageCommands, Cog):
    """stickymessage cog"""

    @Cog.listener("on_valid_message")
    async def _on_msg(self, ctx):
        """proxy message event"""
        await self.on_valid_message(ctx)


async def setup(bot):
    """load stickymessage cog"""
    await bot.add_cog(Stickymessage(bot))
