from __future__ import annotations

from asyncio import Lock
from collections import defaultdict

from discord.ext import commands
from typing import TYPE_CHECKING

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
from .extended.disable.module.module import ModuleDisableCommands
from .extended.enable.command.command import CommandEnableCommands
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
from .extended.steal.steal import Steal
from .extended.embedcode.embedcode import Embedcode
from .extended.embed.embed import EmbedCommands
from .events import ServerEvents



if TYPE_CHECKING:
    from core.vain import Vain

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
    Steal,
    Embedcode,
    EmbedCommands,
    ServerEvents,
    Package,
    metaclass=_Meta,
):
    """main server extension — all subcommands combined"""

    def __init__(self, bot: Vain) -> None:
        Package.__init__(self, bot)
        self.ar_locks = defaultdict(Lock)
        self.leave_locks = defaultdict(Lock)
        self.join_locks = defaultdict(Lock)
        self.boost_locks = defaultdict(Lock)
        self.sticky_locks = defaultdict(Lock)
        self.pinned_ids = {}


async def setup(bot: Vain) -> None:
    """load server extension"""
    await bot.add_cog(Server(bot))
