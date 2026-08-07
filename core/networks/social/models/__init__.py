"""Models for social network clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SocialPost:
    """Platform-agnostic post payload used by repost containers."""

    platform: str
    url: str
    username: str = "unknown"
    display_name: str = ""
    avatar_url: str | None = None
    caption: str = ""
    media_urls: list[str] = field(default_factory=list)
    is_video: bool = False
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    save_count: int = 0
    play_count: int = 0
    music_title: str | None = None
    music_url: str | None = None
    music_author: str | None = None
    region: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def author_label(self) -> str:
        return self.display_name or self.username

    @property
    def profile_url(self) -> str:
        user = (self.username or "").lstrip("@")
        plat = (self.platform or "").lower()
        if plat == "tiktok" and user:
            return f"https://www.tiktok.com/@{user}"
        if plat == "instagram" and user:
            return f"https://www.instagram.com/{user}/"
        if plat in {"twitter", "x"} and user:
            return f"https://x.com/{user}"
        if plat == "youtube" and user:
            handle = user if user.startswith("@") else f"@{user}"
            return f"https://www.youtube.com/{handle}"
        if plat == "telegram" and user:
            return f"https://t.me/{user}"
        return self.url


__all__ = ["SocialPost"]
