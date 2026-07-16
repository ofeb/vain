"""vainapi — internal social / web API clients."""

from .instagram import Instagram

# Optional exports — other clients may pull heavier third-party deps.
try:
    from .tiktok import TikTok
except Exception:  # pragma: no cover
    TikTok = None  # type: ignore

try:
    from .brave import Brave
except Exception:  # pragma: no cover
    Brave = None  # type: ignore

try:
    from .github import GitHub
except Exception:  # pragma: no cover
    GitHub = None  # type: ignore

try:
    from .twitter import Twitter
except Exception:  # pragma: no cover
    Twitter = None  # type: ignore

try:
    from .reddit import Reddit
except Exception:  # pragma: no cover
    Reddit = None  # type: ignore

__all__ = [
    "Instagram",
    "TikTok",
    "Brave",
    "GitHub",
    "Twitter",
    "Reddit",
]
