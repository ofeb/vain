"""Instagram post client — vain.rest primary (docs: https://vain.rest/docs)."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from core.api import VainRest
from .models import SocialPost

log = logging.getLogger("vain.social.instagram")

_SHORT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/(?P<code>[\w-]+)",
    re.I,
)


def is_instagram_url(url: str) -> bool:
    u = (url or "").lower()
    return "instagram.com" in u or "instagr.am" in u


def shortcode_from_url(url: str) -> str | None:
    m = _SHORT_RE.search(url or "")
    if m:
        return m.group("code")
    try:
        path = urlparse(url).path.strip("/").split("/")
        for i, part in enumerate(path):
            if part in {"p", "reel", "tv", "reels"} and i + 1 < len(path):
                return path[i + 1]
    except Exception:
        pass
    return None


class Instagram:
    """Instagram post client powered by vain.rest (``/instagram/media`` etc.)."""

    def __init__(self, session=None) -> None:
        self._session = session
        self._api = None

    def _client(self) -> VainRest:
        if self._api is None:
            self._api = VainRest()
        return self._api

    async def close(self) -> None:
        self._api = None

    async def post(self, url: str) -> Optional[SocialPost]:
        """Primary: GET /instagram/media?url=… (vain.rest)."""
        code = shortcode_from_url(url)
        if not code:
            return None
        is_reel = "/reel" in (url or "").lower() or "/reels/" in (url or "").lower()
        clean = (
            f"https://www.instagram.com/reel/{code}/"
            if is_reel
            else f"https://www.instagram.com/p/{code}/"
        )

        try:
            resolved = await self._client().instagram_resolve_media(clean)
        except Exception as exc:
            log.debug("vain.rest resolve_media failed: %s", exc)
            return None

        video_urls = [u for u in (resolved.get("video_urls") or []) if u]
        image_urls = [u for u in (resolved.get("image_urls") or []) if u]

        media_urls = list(dict.fromkeys([*video_urls, *image_urls]))
        is_video = bool(video_urls) or is_reel

        author = str(resolved.get("author_name") or "unknown").lstrip("@")
        caption = str(resolved.get("title") or "")[:2000]
        avatar_url: str | None = None
        display = author

        
        if author and author != "unknown":
            try:
                user = await self._client().instagram_get_user(author)
                if user:
                    display = str(user.get("full_name") or author)
                    avatar_url = user.get("avatar") or None
            except Exception as exc:
                log.debug("ig profile enrich failed: %s", exc)

        return SocialPost(
            platform="instagram",
            url=clean,
            username=author,
            display_name=display,
            avatar_url=str(avatar_url) if avatar_url else None,
            caption=caption,
            media_urls=media_urls,
            is_video=is_video and (bool(video_urls) or len(image_urls) <= 1),
            raw={
                "source": resolved.get("source") or "vain.rest",
                "code": code,
                "carousel_count": len(image_urls),
            },
        )

    async def profile(self, username: str) -> Optional[dict]:
        username = (username or "").strip().lstrip("@")
        if not username:
            return None
        try:
            user = await self._client().instagram_get_user(username)
            return {
                "pk": user["pk"],
                "username": user["username"],
                "full_name": user["full_name"],
                "is_private": user["is_private"],
                "is_verified": user["is_verified"],
                "media_count": user["media_count"],
                "follower_count": user["followers"],
                "following_count": user["following"],
                "biography": user["biography"],
                "profile_pic_url": user["avatar"],
                "profile_pic_url_hd": user["avatar"],
            }
        except Exception as exc:
            log.debug("ig profile failed: %s", exc)
            return None
