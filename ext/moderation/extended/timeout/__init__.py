from __future__ import annotations

"""Timeout commands live in the main ModerationCommands cog.

This package exists only for structural consistency with other extended
modules. All timeout / untimeout / timeout list functionality is implemented
in ext/moderation/__init__.py (ModerationCommands).
"""

from core.discord.package import Package


class Timeout(Package):
    """Placeholder - timeout is implemented in ModerationCommands."""

    pass
