from __future__ import annotations

from discord.ext import commands

from core.discord.mixin import _Meta

from .moderation import ModerationCommands
from .extended.nuke.nuke import Nuke
from .extended.thread.thread import Thread
from .extended.lockdown.lockdown import Lockdown
from .extended.remind.remind import Remind
from .extended.role.role import Role
from .extended.purge.purge import Purge
from .extended.history.history import History
from .extended.proof.proof import Proof
from .extended.notes.notes import Notes
from .extended.timeout.timeout import Timeout
from .extended.slowmode.slowmode import Slowmode
from .extended.revokefiles.revokefiles import Revokefiles
from .extended.restrictcommand.restrictcommand import Restrictcommand
from .extended.stickyrole.stickyrole import Stickyrole
from .extended.forcenickname.forcenickname import Forcenickname


class Moderation(
    ModerationCommands,
    Nuke,
    Thread,
    Lockdown,
    Remind,
    Role,
    Purge,
    History,
    Proof,
    Notes,
    Timeout,
    Slowmode,
    Revokefiles,
    Restrictcommand,
    Stickyrole,
    Forcenickname,
    commands.Cog,
    metaclass=_Meta,
):
    """main moderation extension — all subcommands combined"""


async def setup(bot) -> None:
    """load moderation extension"""
    await bot.add_cog(Moderation(bot))
