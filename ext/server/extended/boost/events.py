from __future__ import annotations

import logging

from core.discord.package import Package

from .boost import BoostCommands

log = logging.getLogger("vain.boost")


class BoostEvents(Package):
    @Package.listener("on_member_update")
    async def _boost_listener(self, before, after) -> None:
        if before.premium_since == after.premium_since or after.premium_since is None:
            return
        log.info("[BOOST] member_update boost detected for %s in %s", after, after.guild)
        await BoostCommands.on_member_boost(self, after)
