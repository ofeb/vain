from discord.ext.commands import Cog
from .pagination import PaginationCommands


class Pagination(PaginationCommands, Cog):
    """pagination cog"""

    @Cog.listener("on_raw_reaction_add")
    async def _on_reaction(self, payload):
        """proxy reaction event"""
        await self.on_raw_reaction_add(payload)

    @Cog.listener("on_paginator_update")
    async def _on_page_update(self, message, row, page):
        """proxy page update"""
        await self.on_paginator_update(message, row, page)


async def setup(bot):
    """load pagination cog"""
    await bot.add_cog(Pagination(bot))
