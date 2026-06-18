from discord.ext.commands import Cog
from .autoresponder import AutoresponderCommands


class Autoresponder(AutoresponderCommands, Cog):
    """autoresponder cog"""

    @Cog.listener("on_context")
    async def _on_ctx(self, ctx):
        """proxy context event"""
        await self.on_context(ctx)


async def setup(bot):
    """load autoresponder cog"""
    await bot.add_cog(Autoresponder(bot))
