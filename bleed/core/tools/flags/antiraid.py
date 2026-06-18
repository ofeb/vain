"""antiraid command flags definition.
used when parsing antiraid setup commands.
extends discord.py FlagConverter"""

from discord.ext.commands import FlagConverter, flag
from typing import Optional


class AntiRaidFlags(FlagConverter, prefix='--', delimiter=' '):
    """flags for antiraid config"""
    joins: Optional[int] = flag(default=10, description='joins per window before trigger')
    window: Optional[int] = flag(default=10, description='time window in seconds')
    punishment: Optional[str] = flag(default='ban', description='ban kick or lockdown')
    age: Optional[int] = flag(default=0, description='min account age in days')
