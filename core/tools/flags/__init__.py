"""flag converters for command argument parsing.
each file defines flags for a specific feature.
from core.tools.flags import AntiNukeFlags AutomodFlags"""

from .antinuke import AntiNukeFlags
from .antiraid import AntiRaidFlags
from .automod import AutomodFlags, FilterFlags, SpamFilterFlags
from .guilds import Parameters
from .lastfm import LastFMFlags

__all__ = [
    "AntiNukeFlags",
    "AntiRaidFlags",
    "AutomodFlags",
    "FilterFlags",
    "SpamFilterFlags",
    "Parameters",
    "LastFMFlags",
]
