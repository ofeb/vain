from __future__ import annotations

from core.discord.package import Package

from .settings import SettingsCommands


class SettingsEvents(Package):
    @Package.listener("on_vanity_change")
    async def _tracker_vanity_listener(self, vanity) -> None:
        await SettingsCommands.on_vanity_change(self, vanity)

    @Package.listener("on_username_change")
    async def _tracker_username_listener(self, username) -> None:
        await SettingsCommands.on_username_change(self, username)
