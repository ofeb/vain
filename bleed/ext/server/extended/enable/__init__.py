from __future__ import annotations
from discord import Client
from .commands import Commands


class Enable(Commands):
    """server enable cog"""
    def __init__(self, bot: Client):
        Commands.__init__(self, bot)


async def setup(bot: Client) -> None:
    await bot.add_cog(Enable(bot))
