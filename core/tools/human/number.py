"""human readable number formatting.
converts large numbers to short forms like 1k 2m.
also handles file sizes and percentages"""

from humanize import intword
from typing import Union


def compact(n: Union[int, float]) -> str:
    """shorten a number to k m b t suffix.
    eg 1500 becomes 1.5k and 2000000 becomes 2m.
    strips trailing .0 from results"""
    out = intword(int(n))
    return (
        out.replace(" million", "m")
           .replace(" billion", "b")
           .replace(" trillion", "t")
           .replace(" thousand", "k")
           .replace(".0k", "k")
           .replace(".0m", "m")
           .replace(".0b", "b")
           .replace(".0t", "t")
    )


def filesize(n: int) -> str:
    """convert bytes to human readable file size string"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def clamp(value: Union[int, float], low: Union[int, float], high: Union[int, float]) -> Union[int, float]:
    """clamp value between low and high inclusive"""
    return max(low, min(high, value))
