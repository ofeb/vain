from __future__ import annotations
from discord.ext import commands

from core.discord.mixin import _Meta

from .command.command import CommandEnableCommands
from .event.event import EventEnableCommands
from .module.module import ModuleEnableCommands


class Enable(
    CommandEnableCommands,
    EventEnableCommands,
    ModuleEnableCommands,
    commands.Cog,
    metaclass=_Meta,
):
    """server enable cog"""


async def setup(bot) -> None:
    await bot.add_cog(Enable(bot))
