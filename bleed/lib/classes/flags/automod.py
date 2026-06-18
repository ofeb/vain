from __future__ import annotations

from typing import Optional

from discord.ext.commands import FlagConverter, flag


class FilterFlags(FlagConverter, prefix="--", delimiter=" "):
    threshold: Optional[int] = flag(default=3)
    punishment: Optional[str] = flag(default="delete")


class SpamFilterFlags(FlagConverter, prefix="--", delimiter=" "):
    threshold: Optional[int] = flag(default=5)
    punishment: Optional[str] = flag(default="delete")
