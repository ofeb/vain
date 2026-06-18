from __future__ import annotations

from discord.ext import commands

from core.discord.mixin import _Meta

from .server import ServerCommands
from .extended.alias.alias import AliasCommands
from .extended.autoresponder.autoresponder import AutoresponderCommands
from .extended.badge.badge import BadgeCommands
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


async def setup(bot) -> None:
    """load server extension"""
    await bot.add_cog(Server(bot))
