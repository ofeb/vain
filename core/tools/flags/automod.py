"""automod command flags definition.
used when parsing automod filter setup commands.
extends discord.py FlagConverter"""

from __future__ import annotations

from typing import Optional

from discord.ext.commands import FlagConverter, flag


class AutomodFlags(FlagConverter, prefix="--", delimiter=" "):
    """flags for automod filter config"""

    threshold: Optional[int] = flag(default=3, description="how many violations before action")
    punishment: Optional[str] = flag(default="delete", description="delete mute warn or kick")
    duration: Optional[int] = flag(default=10, description="mute duration in minutes")
    ignore_roles: Optional[str] = flag(default=None, description="role ids to ignore")
    ignore_channels: Optional[str] = flag(default=None, description="channel ids to ignore")


class FilterFlags(FlagConverter, prefix="--", delimiter=" "):
    """flags for filter add/edit commands"""

    threshold: Optional[int] = flag(default=3)
    punishment: Optional[str] = flag(default="delete")


class SpamFilterFlags(FlagConverter, prefix="--", delimiter=" "):
    """flags for spam filter setup"""

    threshold: Optional[int] = flag(default=5)
    punishment: Optional[str] = flag(default="delete")
