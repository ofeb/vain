"""Guild message / boost script flags."""

from __future__ import annotations

from discord.ext.commands import FlagConverter, flag

from core.tools.embed import parse_duration_token


class _DurationFlag(int):
    """int flag value that also accepts ``5m`` / ``5mins`` / ``1h`` / ``10s`` tokens."""

    def __new__(cls, value):
        text = str(value).strip().lower()
        if not text.isdigit():
            seconds = parse_duration_token(text)
            if seconds is None:
                raise ValueError(
                    f"Invalid duration: `{value}` - use 5s, 5m, 5mins, 1h, 1hour or 10."
                )
            value = seconds
        return int.__new__(cls, int(value))


class Parameters(FlagConverter, case_insensitive=True, prefix="--", delimiter=" "):
    self_destruct: _DurationFlag | None = flag(aliases=["delete_after"], default=None)
    twoboosts: bool = flag(
        name="twoboosts",
        aliases=["2ndboost", "tb", "2", "secondboost"],
        default=False,
    )
