from __future__ import annotations

from core.discord.package import Package

from .. import SuggestCommands


class SuggestEvents(Package):
    @Package.listener("on_raw_reaction_add")
    async def _suggest_reaction_add_listener(self, payload) -> None:
        await SuggestCommands.suggest_reaction_add(self, payload)

    @Package.listener("on_raw_reaction_remove")
    async def _suggest_reaction_remove_listener(self, payload) -> None:
        await SuggestCommands.suggest_reaction_remove(self, payload)
