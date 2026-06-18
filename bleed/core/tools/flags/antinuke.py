"""antinuke command flags definition.
used when parsing antinuke setup commands.
extends discord.py FlagConverter"""

from discord.ext.commands import FlagConverter, flag
from typing import Optional


class AntiNukeFlags(FlagConverter, prefix='--', delimiter=' '):
    """flags for antinuke command config"""
    ban: Optional[int] = flag(default=None, description='max bans before trigger')
    kick: Optional[int] = flag(default=None, description='max kicks before trigger')
    role: Optional[int] = flag(default=None, description='max role deletes before trigger')
    channel: Optional[int] = flag(default=None, description='max channel deletes before trigger')
    webhook: Optional[int] = flag(default=None, description='max webhooks before trigger')
    punishment: Optional[str] = flag(default='ban', description='ban kick or strip')
