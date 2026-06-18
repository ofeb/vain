"""antiraid command flags definition.
used when parsing antiraid setup commands.
extends discord.py FlagConverter"""

from discord.ext.commands import FlagConverter, flag
from typing import Optional


class AntiRaidFlags(FlagConverter, prefix='--', delimiter=' '):
    """flags for antiraid config"""
    punishment: Optional[str] = flag(
        aliases=["action", "do"],
        default=None,
        description="ban or kick",
    )
    threshold: Optional[int] = flag(
        default=None,
        description="join or age threshold depending on the module",
    )
    lock: Optional[bool] = flag(
        default=None,
        description="lock channels when a massjoin tripwire is hit",
    )
    punish: Optional[bool] = flag(
        default=None,
        description="punish new joins for a short window after massjoin triggers",
    )
