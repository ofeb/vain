from __future__ import annotations

from discord.ext.commands import FlagConverter, flag


class Parameters(FlagConverter, case_insensitive=True, prefix="--", delimiter=" "):
    self_destruct: int | None = flag(aliases=["delete_after"], default=None)
    
    twoboosts: bool = flag(
        name="twoboosts",
        aliases=["2ndboost", "tb", "2", "secondboost"],
        default=False,
    )
