from __future__ import annotations

from core.discord.package import Package

from .goodbye import GoodbyeCommands


class GoodbyeEvents(Package):
    @Package.listener("on_member_remove")
    async def _goodbye_listener(self, member) -> None:
        await GoodbyeCommands.on_member_remove(self, member)
