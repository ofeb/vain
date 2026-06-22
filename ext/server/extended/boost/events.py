from __future__ import annotations

from core.discord.package import Package

from .boost import BoostCommands


class BoostEvents(Package):
    @Package.listener("on_member_update")
    async def _boost_listener(self, before, after) -> None:
        if before.premium_since == after.premium_since or after.premium_since is None:
            return
        await BoostCommands.on_member_boost(self, after)
