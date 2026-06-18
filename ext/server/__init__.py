from __future__ import annotations

from asyncio import Lock
from collections import defaultdict

from discord.ext import commands

from core.discord.mixin import _Meta
from core.discord.package import Package

from .server import ServerCommands
from .extended.alias.alias import AliasCommands
from .extended.autoresponder.autoresponder import AutoresponderCommands
from .extended.badge.badge import BadgeCommands
from .extended.boost.boost import BoostCommands
from .extended.boosterrole.boosterrole import BoosterroleCommands
from .extended.customize.customize import CustomizeCommands
from .extended.disable.command.command import CommandDisableCommands
from .extended.disable.event.event import EventDisableCommands
from .extended.disable.module.module import ModuleDisableCommands
from .extended.enable.command.command import CommandEnableCommands
from .extended.enable.event.event import EventEnableCommands
from .extended.enable.module.module import ModuleEnableCommands
from .extended.filter.filter import FilterCommands
from .extended.goodbye.goodbye import GoodbyeCommands
from .extended.ignore.ignore import IgnoreCommands
from .extended.imgonly.imgonly import ImgonlyCommands
from .extended.invoke.invoke import InvokeCommands
from .extended.pagination.pagination import PaginationCommands
from .extended.pin.pin import PinCommands
from .extended.prefix.prefix import PrefixCommands
from .extended.reposter.reposter import ReposterCommands
from .extended.set.set import SetCommands
from .extended.settings.settings import SettingsCommands
from .extended.stickymessage.stickymessage import StickymessageCommands
from .extended.suggest.suggest import SuggestCommands
from .extended.webhook.webhook import WebhookCommands
from .extended.welcome.welcome import WelcomeCommands


class Server(
    ServerCommands,
    PrefixCommands,
    AliasCommands,
    WebhookCommands,
    BoosterroleCommands,
    BoostCommands,
    WelcomeCommands,
    GoodbyeCommands,
    StickymessageCommands,
    InvokeCommands,
    CustomizeCommands,
    PaginationCommands,
    CommandDisableCommands,
    CommandEnableCommands,
    EventDisableCommands,
    EventEnableCommands,
    ModuleDisableCommands,
    ModuleEnableCommands,
    IgnoreCommands,
    AutoresponderCommands,
    ImgonlyCommands,
    FilterCommands,
    PinCommands,
    SetCommands,
    BadgeCommands,
    SettingsCommands,
    ReposterCommands,
    SuggestCommands,
    commands.Cog,
    metaclass=_Meta,
):
    """main server extension — all subcommands combined"""

    def __init__(self, bot) -> None:
        Package.__init__(self, bot)
        self.ar_locks = defaultdict(Lock)
        self.leave_locks = defaultdict(Lock)
        self.join_locks = defaultdict(Lock)
        self.boost_locks = defaultdict(Lock)
        self.sticky_locks = defaultdict(Lock)
        self.pinned_ids = {}

    @commands.Cog.listener("on_member_join")
    async def _welcome_listener(self, member) -> None:
        await WelcomeCommands.on_member_agree(self, member)

    @commands.Cog.listener("on_member_remove")
    async def _goodbye_listener(self, member) -> None:
        await GoodbyeCommands.on_member_remove(self, member)

    @commands.Cog.listener("on_context")
    async def _autoresponder_listener(self, ctx) -> None:
        await AutoresponderCommands.on_context(self, ctx)

    @commands.Cog.listener("on_valid_message")
    async def _sticky_listener(self, ctx) -> None:
        await StickymessageCommands.on_valid_message(self, ctx)

    @commands.Cog.listener("on_raw_reaction_add")
    async def _pagination_reaction_listener(self, payload) -> None:
        await PaginationCommands.on_raw_reaction_add(self, payload)

    @commands.Cog.listener("on_paginator_update")
    async def _pagination_update_listener(self, message, row, page) -> None:
        await PaginationCommands.on_paginator_update(self, message, row, page)

    @commands.Cog.listener("on_vanity_change")
    async def _tracker_vanity_listener(self, vanity) -> None:
        await SettingsCommands.on_vanity_change(self, vanity)

    @commands.Cog.listener("on_username_change")
    async def _tracker_username_listener(self, username) -> None:
        await SettingsCommands.on_username_change(self, username)

    @commands.Cog.listener("on_member_update")
    async def _boost_listener(self, before, after) -> None:
        if before.premium_since == after.premium_since or after.premium_since is None:
            return
        await BoostCommands.on_member_boost(self, after)


async def setup(bot) -> None:
    """load server extension"""
    await bot.add_cog(Server(bot))
