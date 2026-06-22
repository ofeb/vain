from __future__ import annotations

from core.discord.package import Package

from .stickymessage import StickymessageCommands


class StickymessageEvents(Package):
    @Package.listener("on_valid_message")
    async def _sticky_listener(self, ctx) -> None:
        await StickymessageCommands.on_valid_message(self, ctx)
