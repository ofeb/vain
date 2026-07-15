"""Public social / media API clients.

Prefer these entrypoints over importing ``core.api.internal`` directly::

    from core.api import TikTok, Instagram, UDownloader
"""

from __future__ import annotations

from .internal.exceptions import Error
from .internal.instagram import Instagram
from .internal.tiktok import TikTok
from .udownloader import UDownloader

# Optional clients — only import when dependencies are available
try:
    from .internal.brave import Brave
except Exception:  # pragma: no cover
    Brave = None  # type: ignore
try:
    from .internal.github import GitHub
except Exception:  # pragma: no cover
    GitHub = None  # type: ignore
try:
    from .internal.twitter import Twitter
except Exception:  # pragma: no cover
    Twitter = None  # type: ignore
try:
    from .internal.reddit import Reddit
except Exception:  # pragma: no cover
    Reddit = None  # type: ignore

__all__ = [
    "Error",
    "TikTok",
    "Instagram",
    "UDownloader",
    "Brave",
    "GitHub",
    "Twitter",
    "Reddit",
]
