"""automod command flags definition.
used when parsing automod filter setup commands.
extends discord.py FlagConverter"""

from discord.ext.commands import FlagConverter, flag
from typing import Optional


class AutomodFlags(FlagConverter, prefix='--', delimiter=' '):
    """flags for automod filter config"""
    threshold: Optional[int] = flag(default=3, description='how many violations before action')
    punishment: Optional[str] = flag(default='delete', description='delete mute warn or kick')
    duration: Optional[int] = flag(default=10, description='mute duration in minutes')
    ignore_roles: Optional[str] = flag(default=None, description='role ids to ignore')
    ignore_channels: Optional[str] = flag(default=None, description='channel ids to ignore')
