from __future__ import annotations

import logging

from core.discord.package import Package

from .. import StickymessageCommands

log = logging.getLogger("vain.stickymessage")


class StickymessageEvents(Package):
    @Package.listener("on_valid_message")
    async def _sticky_listener(self, ctx) -> None:
        log.debug("[STICKY] on_valid_message fired in %s", ctx.channel)
        await StickymessageCommands.on_valid_message(self, ctx)
