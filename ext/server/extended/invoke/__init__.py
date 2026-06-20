from __future__ import annotations

from discord.ext.commands import Cog

from .invoke import InvokeCommands


class Invoke(InvokeCommands, Cog):
    """invoke message customization cog"""
    __cog_name__ = "Servers"


async def setup(bot) -> None:
    """load invoke cog"""
    await bot.add_cog(Invoke(bot))
