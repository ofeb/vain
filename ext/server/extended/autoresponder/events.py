from __future__ import annotations

from core.discord.package import Package

from .autoresponder import AutoresponderCommands


class AutoresponderEvents(Package):
    @Package.listener("on_context")
    async def _autoresponder_listener(self, ctx) -> None:
        await AutoresponderCommands.on_context(self, ctx)
