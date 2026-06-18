"""antinuke command flags definition."""

from discord.ext.commands import FlagConverter, flag


class AntiNukeFlags(FlagConverter, case_insensitive=True, prefix="--", delimiter=" "):
    """flags shared by the documented antinuke setup commands."""

    punishment: str = flag(
        aliases=["action", "do"],
        default="kick",
        description="ban kick or stripstaff",
    )
    threshold: int = flag(
        default=3,
        description="max actions before trigger",
    )
    command: bool = flag(
        default=False,
        description="count bleed commands toward the threshold",
    )
