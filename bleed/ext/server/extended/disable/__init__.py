from __future__ import annotations
from discord import Client
from .commands import Commands


class Disable(Commands):
    """server disable cog"""
    def __init__(self, bot: Client):
        Commands.__init__(self, bot)


async def setup(bot: Client) -> None:
    await bot.add_cog(Disable(bot))
