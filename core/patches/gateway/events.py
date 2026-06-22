﻿"""gateway event hooks.
registers listeners that run before cog listeners.
handles global checks like blacklists and maintenance"""

from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

from core.discord.package import Package

if TYPE_CHECKING:
    from core.bleed import Bleed


class GatewayEvents(Package):
    """global pre-processing event handlers.
    intercepts all messages before command processing.
    checks blacklist and disabled modules"""


    @Package.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if await self.bot.db.fetchrow(
            "SELECT 1 FROM blacklist WHERE user_id = $1", message.author.id
        ):
            return
        await self.bot.process_commands(message)


async def setup(bot: Bleed):
    await bot.add_cog(GatewayEvents(bot))
