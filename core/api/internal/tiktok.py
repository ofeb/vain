"""TikTok client — scrape web rehydration data for metadata + play URL."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncio
import json

from .exceptions import Error
from .http import State, _munchify
from .models import TikTokStats, TikTokUser, TikTokVideo

TIKTOK_REGEX = re.compile(
    r"^.*https?://(?:m|www|vm|vt)?\.?tiktok\.com/"
    r"((?:.*\b(?:(?:v|embed|photo|video|t)/|\?shareId=|&item_id=)(\d+))|\w+)",
    re.I,
)
REHYDRATION_REGEX = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.S,
)

_DEFAULT_HEADERS = {
    "Referer": "https://www.tiktok.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class TikTok:
    """Public TikTok web scraper (no official API key required)."""

    def __init__(self, *, cookies: str | None = None) -> None:
        self.session = State()
        self.headers = dict(_DEFAULT_HEADERS)
        if cookies:
            self.headers["Cookie"] = cookies

    async def resolve_url(self, url: str) -> str:
        """Follow short links (vm/vt) to the final tiktok.com URL."""
        url = (url or "").strip()
        if not url.startswith("http"):
            url = "https://" + url
        host = urlparse(url).netloc.lower()
        if "vm.tiktok" not in host and "vt.tiktok" not in host:
            return url
        try:
            # State returns body; use aiohttp for redirect resolution
            from aiohttp import ClientSession

            async with ClientSession(headers=self.headers) as cs:
                async with cs.get(url, allow_redirects=True, max_redirects=10) as resp:
                    return str(resp.url)
        except Exception:
            return url

    async def get_user(self, username: str) -> TikTokUser:
        username = (username or "").lstrip("@").strip()
        if not username:
            raise Error("Username is required.")

        data = await self.session.request(
            "GET",
            f"https://www.tiktok.com/@{username}",
            headers=self.headers,
        )
        raw = self._rehydrate(data)
        detail = raw["__DEFAULT_SCOPE__"]["webapp.user-detail"]
        loaded = _munchify(detail)

        if getattr(loaded, "statusCode", None) == 10221:
            raise Error(f"Can't find a user with the username `@{username}`.")

        user_info = loaded.userInfo
        stats = TikTokStats.model_validate(user_info.stats.__dict__ if hasattr(user_info.stats, "__dict__") else user_info.stats)
        user_data = user_info.user.__dict__ if hasattr(user_info.user, "__dict__") else dict(user_info.user)
        if isinstance(user_data, dict):
            user_data["stats"] = stats.model_dump(by_alias=True)
        return TikTokUser.model_validate(user_data if isinstance(user_data, dict) else user_info.user)

    async def get_video(self, url: str) -> TikTokVideo:
        """Fetch video metadata and set ``url`` to the CDN play address."""
        if not TIKTOK_REGEX.match(url or ""):
            # Still try resolving short links that may not match yet
            url = await self.resolve_url(url)
            if not TIKTOK_REGEX.match(url or ""):
                raise Error("This is not a valid TikTok URL.")

        url = await self.resolve_url(url)
        data = await self.session.request("GET", url, headers=self.headers)
        raw = self._rehydrate(data)
        scope = raw["__DEFAULT_SCOPE__"]
        detail = scope.get("webapp.video-detail") or scope.get("webapp.video-detail".replace("-", "_"))
        if not detail:
            # Try alternate key variants
            for key, value in scope.items():
                if "video" in key.lower() and isinstance(value, dict):
                    detail = value
                    break
        if not detail:
            raise Error("Could not parse TikTok video data.")

        loaded = _munchify(detail)
        item = loaded.itemInfo.itemStruct

        play = None
        video = getattr(item, "video", None)
        if video is not None:
            play = getattr(video, "playAddr", None) or getattr(video, "downloadAddr", None)

        # Convert munch → plain dict for pydantic
        def _to_dict(obj: Any) -> Any:
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {k: _to_dict(v) for k, v in obj.items()}
            if hasattr(obj, "toDict"):
                return _to_dict(obj.toDict())
            if hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes, int, float, bool)):
                try:
                    return {k: _to_dict(v) for k, v in dict(obj).items()}
                except Exception:
                    pass
            return obj

        raw = _to_dict(item) if not isinstance(item, dict) else item
        if not isinstance(raw, dict):
            # munch fallback
            raw = dict(item) if hasattr(item, "items") else {}
            raw = {k: getattr(item, k, None) for k in (
                "id", "desc", "createTime", "stats", "author", "music", "video", "locationCreated"
            )}

        author = raw.get("author") or {}
        if isinstance(author, dict):
            author.setdefault("uniqueId", author.get("unique_id") or author.get("uniqueId") or "")
            author.setdefault("nickname", author.get("nickname") or author.get("uniqueId") or "")
            author.setdefault("signature", author.get("signature") or "")
            author.setdefault("avatarLarger", author.get("avatarLarger") or author.get("avatarThumb") or "")
            author.setdefault("verified", bool(author.get("verified")))
            author.setdefault("privateAccount", bool(author.get("privateAccount")))

        stats = raw.get("stats") or {}
        music = raw.get("music") or {}
        payload = {
            "id": raw.get("id") or 0,
            "desc": raw.get("desc") or raw.get("description") or "",
            "createTime": raw.get("createTime"),
            "stats": stats if isinstance(stats, dict) else {},
            "author": author if isinstance(author, dict) else {},
            "music": music if isinstance(music, dict) else {},
            "url": play or "",
            "locationCreated": raw.get("locationCreated") or raw.get("region"),
            "webpage_url": url,
        }
        return TikTokVideo.model_validate(payload)

    async def download_video(
        self,
        video: TikTokVideo,
        path: str | Path | None = None,
    ) -> Path | BytesIO:
        """Download video bytes (only when a local file is actually needed)."""
        if not video.url:
            raise Error("Video has no playable URL.")
        video_data = await self.session.request("GET", video.url, headers=self.headers)
        if not isinstance(video_data, (bytes, bytearray)):
            raise Error("Unexpected response when downloading video.")

        if path:
            save_path = Path(path)

            def _write() -> None:
                save_path.write_bytes(video_data)

            await asyncio.to_thread(_write)
            return save_path
        return BytesIO(video_data)

    @staticmethod
    def _rehydrate(html: str | Any) -> dict[str, Any]:
        if not isinstance(html, str):
            raise Error("Expected HTML when scraping TikTok.")
        match = REHYDRATION_REGEX.search(html)
        if not match:
            raise Error("Could not find TikTok rehydration data.")
        return json.loads(match.group(1))
