"""antinuke command flags definition."""

from typing import Optional

from discord.ext.commands import FlagConverter, flag


class AntiNukeFlags(FlagConverter, case_insensitive=True, prefix="--", delimiter=" "):
    """flags shared by antinuke module toggles."""

    punishment: str = flag(
        aliases=["action", "do"],
        default="kick",
        description="ban, hardban, softban, timeout <time>, jail <time>, kick, warn, stripstaff",
    )
    threshold: int = flag(
        default=3,
        description="max actions before trigger (1-6)",
    )
    command: bool = flag(
        default=False,
        description="count bot commands and manual actions toward the threshold",
    )
    within: Optional[str] = flag(
        aliases=["window", "time"],
        default=None,
        description="time window for the threshold (e.g. 5m). omit for indefinite short window",
    )
