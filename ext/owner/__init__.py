from __future__ import annotations

from discord.ext import commands


async def setup(bot: commands.Bot) -> None:
    from .owner import Owner
    from .events import OwnerEvents

    await bot.add_cog(Owner(bot))
    await bot.add_cog(OwnerEvents(bot))
