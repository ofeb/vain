from __future__ import annotations

from core.discord.package import Package

from .extended.autoresponder.autoresponder import AutoresponderCommands
from .extended.boost.boost import BoostCommands
from .extended.goodbye.goodbye import GoodbyeCommands
from .extended.pagination.pagination import PaginationCommands
from .extended.settings.settings import SettingsCommands
from .extended.stickymessage.stickymessage import StickymessageCommands
from .extended.suggest.suggest import SuggestCommands
from .extended.welcome.welcome import WelcomeCommands


class ServerEvents(Package):
    """Server-wide event listeners."""

    @Package.listener("on_member_join")
    async def _welcome_listener(self, member) -> None:
        await WelcomeCommands.on_member_agree(self, member)

    @Package.listener("on_member_remove")
    async def _goodbye_listener(self, member) -> None:
        await GoodbyeCommands.on_member_remove(self, member)

    @Package.listener("on_context")
    async def _autoresponder_listener(self, ctx) -> None:
        await AutoresponderCommands.on_context(self, ctx)

    @Package.listener("on_valid_message")
    async def _sticky_listener(self, ctx) -> None:
        await StickymessageCommands.on_valid_message(self, ctx)

    @Package.listener("on_raw_reaction_add")
    async def _pagination_reaction_listener(self, payload) -> None:
        await PaginationCommands.on_raw_reaction_add(self, payload)

    @Package.listener("on_raw_reaction_add")
    async def _suggest_reaction_add_listener(self, payload) -> None:
        await SuggestCommands.suggest_reaction_add(self, payload)

    @Package.listener("on_raw_reaction_remove")
    async def _suggest_reaction_remove_listener(self, payload) -> None:
        await SuggestCommands.suggest_reaction_remove(self, payload)

    @Package.listener("on_paginator_update")
    async def _pagination_update_listener(self, message, row, page) -> None:
        await PaginationCommands.on_paginator_update(self, message, row, page)

    @Package.listener("on_vanity_change")
    async def _tracker_vanity_listener(self, vanity) -> None:
        await SettingsCommands.on_vanity_change(self, vanity)

    @Package.listener("on_username_change")
    async def _tracker_username_listener(self, username) -> None:
        await SettingsCommands.on_username_change(self, username)

    @Package.listener("on_member_update")
    async def _boost_listener(self, before, after) -> None:
        if before.premium_since == after.premium_since or after.premium_since is None:
            return
        await BoostCommands.on_member_boost(self, after)
