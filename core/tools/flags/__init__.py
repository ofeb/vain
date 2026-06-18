"""flag converters for command argument parsing.
each file defines flags for a specific feature.
from core.tools.flags import AntiNukeFlags AutomodFlags"""

from .antinuke import AntiNukeFlags
from .automod import AutomodFlags
from .antiraid import AntiRaidFlags
from .lastfm import LastFMFlags

__all__ = ["AntiNukeFlags", "AutomodFlags", "AntiRaidFlags", "LastFMFlags"]
