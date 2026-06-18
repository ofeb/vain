from __future__ import annotations
from discord.ext import commands

from core.discord.mixin import _Meta

from .command.command import CommandDisableCommands
from .event.event import EventDisableCommands
from .module.module import ModuleDisableCommands


class Disable(
    CommandDisableCommands,
    EventDisableCommands,
    ModuleDisableCommands,
    commands.Cog,
    metaclass=_Meta,
):
    """server disable cog"""


async def setup(bot) -> None:
    await bot.add_cog(Disable(bot))
