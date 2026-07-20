from __future__ import annotations

import logging

from core.discord.package import Package

from .. import AutoresponderCommands

log = logging.getLogger("vain.autoresponder")


class AutoresponderEvents(Package):
    @Package.listener("on_context")
    async def _autoresponder_listener(self, ctx) -> None:
        log.debug("[AUTO] on_context fired for %s", ctx.message.content[:50])
        await AutoresponderCommands.on_context(self, ctx)
