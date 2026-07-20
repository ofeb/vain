from __future__ import annotations

import logging

from core.discord.package import Package

from ..goodbye import GoodbyeCommands

log = logging.getLogger("vain.goodbye")


class GoodbyeEvents(Package):
    @Package.listener("on_member_remove")
    async def _goodbye_listener(self, member) -> None:
        log.info("[GOODBYE] member_remove fired for %s in %s", member, member.guild)
        await GoodbyeCommands.on_member_remove(self, member)
