"""Instagram client — wraps vainapi (cookie-free public download APIs)."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

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


def _looks_like_video(url: str) -> bool:
    lu = (url or "").lower()
    return any(
        t in lu
        for t in (".mp4", "video", "play_video", "/v/t2/", "/v/t16/", "/v/t50/")
    )


class Instagram:
    """Instagram post client powered by vainapi (no session cookies)."""

    def __init__(self, session=None) -> None:
        self._session = session
        self._api = None

    def _client(self):
        if self._api is None:
            from core.api.internal.instagram import Instagram as VainApiIG

            self._api = VainApiIG()
        return self._api

    async def close(self) -> None:
        self._api = None

    async def post(self, url: str) -> Optional[SocialPost]:
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
            resolved = await self._client().resolve_media(clean)
        except Exception as exc:
            log.debug("vainapi resolve_media failed: %s", exc)
            return None

        video_urls = [u for u in (resolved.get("video_urls") or []) if u]
        image_urls = [u for u in (resolved.get("image_urls") or []) if u]
        media_urls = video_urls or image_urls
        is_video = bool(video_urls) or is_reel

        author = resolved.get("author_name") or "unknown"
        caption = str(resolved.get("title") or "")[:2000]

        return SocialPost(
            platform="instagram",
            url=clean,
            username=str(author).lstrip("@"),
            display_name=str(author),
            avatar_url=None,
            caption=caption,
            media_urls=media_urls,
            is_video=is_video,
            raw={"source": resolved.get("source"), "code": code},
        )

    async def profile(self, username: str) -> Optional[dict]:
        username = (username or "").strip().lstrip("@")
        if not username:
            return None
        try:
            user = await self._client().get_user(username)
            return {
                "pk": user.pk,
                "username": user.username,
                "full_name": user.full_name,
                "is_private": user.is_private,
                "is_verified": user.is_verified,
                "media_count": user.media_count,
                "follower_count": user.followers,
                "following_count": user.following,
                "biography": user.biography,
                "profile_pic_url": user.avatar,
                "profile_pic_url_hd": user.avatar,
            }
        except Exception as exc:
            log.debug("ig profile failed: %s", exc)
            return None
