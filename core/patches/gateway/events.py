"""gateway event hooks.
registers listeners that run before cog listeners.
handles global checks like blacklists and maintenance"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.discord.package import Package

if TYPE_CHECKING:
    from core.vain import Vain


class GatewayEvents(Package):
    """global pre-processing event handlers.

    Message command dispatch lives solely on ``Vain.on_message``. This cog used
    to call ``process_commands`` as well, which double-invoked every command.
    """


async def setup(bot: Vain):
    await bot.add_cog(GatewayEvents(bot))
