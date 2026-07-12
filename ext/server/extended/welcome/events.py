from __future__ import annotations

import logging

from core.discord.package import Package

from .welcome import WelcomeCommands

log = logging.getLogger("vain.welcome")


class WelcomeEvents(Package):
    @Package.listener("on_member_join")
    async def _welcome_listener(self, member) -> None:
        log.info("[WELCOME] member_join fired for %s in %s", member, member.guild)
        await WelcomeCommands.on_member_agree(self, member)
