from __future__ import annotations

from core.discord.package import Package

from .welcome import WelcomeCommands


class WelcomeEvents(Package):
    @Package.listener("on_member_join")
    async def _welcome_listener(self, member) -> None:
        await WelcomeCommands.on_member_agree(self, member)
