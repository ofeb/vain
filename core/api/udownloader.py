"""Lightweight media extractor (yt-dlp based).

Used as the **first** TikTok source for a direct playable URL.
If extraction fails, callers should fall back to ``core.api.TikTok``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("vain.api.udownloader")


@dataclass
class MediaResult:
    """Normalized extract result."""

    url: str
    play_url: str | None = None
    title: str = ""
    uploader: str = ""
    uploader_id: str = ""
    thumbnail: str | None = None
    description: str = ""
    like_count: int = 0
    comment_count: int = 0
    view_count: int = 0
    repost_count: int = 0
    duration: float | None = None
    webpage_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def media_url(self) -> str | None:
        return self.play_url


class UDownloader:
    """Extract playable media URLs without writing files to disk."""

    def __init__(self, *, timeout: float = 14.0) -> None:
        self.timeout = timeout

    async def extract(self, url: str) -> MediaResult | None:
        """Return media metadata + best playable URL, or ``None`` on failure."""
        url = (url or "").strip()
        if not url:
            return None
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._extract_sync, url),
                timeout=self.timeout,
            )
        except Exception as exc:
            log.debug("udownloader extract failed for %s: %s", url, exc)
            return None
        if not info:
            return None
        play = self._best_play_url(info)
        if not play:
            return None
        return MediaResult(
            url=str(info.get("webpage_url") or url),
            play_url=play,
            title=str(info.get("title") or ""),
            uploader=str(info.get("uploader") or info.get("creator") or ""),
            uploader_id=str(info.get("uploader_id") or info.get("channel_id") or ""),
            thumbnail=info.get("thumbnail"),
            description=str(info.get("description") or info.get("title") or ""),
            like_count=int(info.get("like_count") or 0),
            comment_count=int(info.get("comment_count") or 0),
            view_count=int(info.get("view_count") or 0),
            repost_count=int(info.get("repost_count") or 0),
            duration=info.get("duration"),
            webpage_url=str(info.get("webpage_url") or url),
            raw=info,
        )

    @staticmethod
    def _extract_sync(url: str) -> dict[str, Any]:
        import yt_dlp

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 12,
            "format": "best[ext=mp4]/best",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    @staticmethod
    def _best_play_url(info: dict[str, Any]) -> str | None:
        if info.get("url") and str(info["url"]).startswith("http"):
            return str(info["url"])
        # Prefer progressive mp4 formats
        formats = list(info.get("formats") or [])
        scored: list[tuple[int, str]] = []
        for fmt in formats:
            u = fmt.get("url")
            if not u or not str(u).startswith("http"):
                continue
            vcodec = fmt.get("vcodec") or "none"
            acodec = fmt.get("acodec") or "none"
            if vcodec == "none":
                continue
            score = 0
            if acodec != "none":
                score += 50
            if str(fmt.get("ext") or "").lower() == "mp4":
                score += 20
            score += int(fmt.get("height") or 0)
            scored.append((score, str(u)))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]
        return None
