from __future__ import annotations

from core.discord.package import Package

from .pagination import PaginationCommands


class PaginationEvents(Package):
    @Package.listener("on_raw_reaction_add")
    async def _pagination_reaction_listener(self, payload) -> None:
        await PaginationCommands.on_raw_reaction_add(self, payload)

    @Package.listener("on_paginator_update")
    async def _pagination_update_listener(self, message, row, page) -> None:
        await PaginationCommands.on_paginator_update(self, message, row, page)
