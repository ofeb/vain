"""lastfm command flags definition.
used for lastfm now playing and custom commands.
extends discord.py FlagConverter"""

from discord.ext.commands import FlagConverter, flag
from typing import Optional


class LastFMFlags(FlagConverter, prefix='--', delimiter=' '):
    """flags for lastfm embed customization"""
    template: Optional[str] = flag(default=None, description='embed script template')
    reply: Optional[bool] = flag(default=True, description='reply to original message')
    reactions: Optional[str] = flag(default=None, description='emoji reactions to add')
