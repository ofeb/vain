"""Instagram client via i.instagram.com (optional session cookies)."""

from __future__ import annotations

import re
from asyncio import Semaphore, sleep
from random import uniform
from typing import Any, Optional
from urllib.parse import urlparse

from .exceptions import Error
from .http import State, _get
from .models import (
    InstagramComment,
    InstagramFollowerUser,
    InstagramHighlight,
    InstagramMedia,
    InstagramStory,
    InstagramUser,
)

INSTAGRAM_REGEX = re.compile(
    r"^(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/([A-Za-z0-9_-]+)",
    re.I,
)
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def shortcode_to_media_id(code: str) -> int:
    media_id = 0
    for ch in code:
        media_id = media_id * 64 + _ALPHABET.index(ch)
    return media_id


def shortcode_from_url(url: str) -> str | None:
    match = INSTAGRAM_REGEX.match(url or "")
    if match:
        return match.group(1)
    try:
        parts = [p for p in urlparse(url).path.split("/") if p]
        for i, part in enumerate(parts):
            if part in {"p", "reel", "tv", "reels"} and i + 1 < len(parts):
                return parts[i + 1]
    except Exception:
        pass
    return None


class Instagram:
    """Instagram unofficial API using i.instagram.com mobile endpoints."""

    def __init__(
        self,
        csrf: str = "",
        session_id: str = "",
        proxy: str | None = None,
        *,
        cookie_header: str | None = None,
    ) -> None:
        self.session = State()
        self.proxy = proxy
        cookie = cookie_header or ""
        if not cookie and (csrf or session_id):
            parts = []
            if csrf:
                parts.append(f"csrftoken={csrf}")
            if session_id:
                parts.append(f"sessionid={session_id}")
            cookie = "; ".join(parts)
        self.headers = {
            "User-Agent": (
                "Instagram 192.0.0.37.107 Android (28/9; 420dpi; 1080x1920; "
                "samsung; SM-G975F; beyond2; exynos9820; en_US; 301484483)"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US",
            "X-IG-App-ID": "936619743392459",
            "X-IG-Capabilities": "3brTvw==",
            "X-IG-Connection-Type": "WIFI",
        }
        if cookie:
            self.headers["Cookie"] = cookie

    @classmethod
    def from_config(cls) -> "Instagram":
        """Build a client from ``values.api.instagram`` cookies when present."""
        try:
            from core.managers.values import api as api_cfg

            cookie = api_cfg.instagram.cookie_header()
            return cls(cookie_header=cookie or None)
        except Exception:
            return cls()

    async def _request(
        self,
        method: str,
        url: str,
        max_concurrent: int = 3,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> Any:
        async with Semaphore(max_concurrent):
            last_exc: Exception | None = None
            for _ in range(max_retries):
                try:
                    await sleep(uniform(0.15, 0.45))
                    kwargs.setdefault("headers", self.headers)
                    if self.proxy:
                        kwargs.setdefault("proxy", self.proxy)
                    return await self.session.request(method, url, **kwargs)
                except Exception as exc:
                    last_exc = exc
            if last_exc:
                raise last_exc
            raise Error("Instagram request failed.")

    async def get_user(self, username: str) -> InstagramUser:
        username = (username or "").lstrip("@").strip()
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
        )
        user = None
        if hasattr(data, "data") and getattr(data.data, "user", None):
            user = data.data.user
        elif getattr(data, "user", None):
            user = data.user
        if not user:
            # legacy usernameinfo
            data = await self._request(
                "GET",
                f"https://i.instagram.com/api/v1/users/{username}/usernameinfo/",
            )
            user = getattr(data, "user", None)
        if not user:
            raise Error(f"Can't find a user with the username `{username}`.")
        return InstagramUser(**user)

    async def get_post(self, url: str, amount: Optional[int] = None) -> list[InstagramMedia]:
        code = shortcode_from_url(url or "")
        if not code:
            raise Error("This is not a valid Instagram post URL.")

        media_id = shortcode_to_media_id(code)
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/media/{media_id}/info/",
        )
        items = list(getattr(data, "items", None) or [])
        if not items:
            raise Error("Could not load that Instagram post.")

        medias: list[Any] = []
        for media in items:
            if getattr(media, "carousel_media", None):
                for slide in media.carousel_media:
                    if getattr(slide, "image_versions2", None):
                        media.image_urls = [
                            media_url.url for media_url in slide.image_versions2.candidates
                        ]
                    if getattr(slide, "video_versions", None):
                        media.video_url = max(
                            slide.video_versions,
                            key=lambda x: (x.height or 0) * (x.width or 0),
                        ).url
            if getattr(media, "video_versions", None):
                media.video_url = max(
                    media.video_versions,
                    key=lambda x: (x.height or 0) * (x.width or 0),
                ).url
            if getattr(media, "image_versions2", None):
                urls = [media_url.url for media_url in media.image_versions2.candidates]
                if amount:
                    urls = urls[:amount]
                media.image_urls = urls
                media.thumbnail_url = max(
                    media.image_versions2.candidates,
                    key=lambda x: (x.height or 0) * (x.width or 0),
                ).url
            medias.append(media)

        return [InstagramMedia(**m) for m in medias]

    async def get_story(self, username: str, amount: Optional[int] = None) -> list[InstagramStory]:
        user_id = (await self.get_user(username)).pk
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/feed/user/{user_id}/story/",
        )
        reel = _get(data, "reel", {}) or {}
        items = list(_get(reel, "items", []) or [])
        if amount:
            items = items[:amount]
        stories = []
        for story in items:
            if _get(story, "video_versions"):
                story.video_url = max(
                    story.video_versions,
                    key=lambda x: x.height * x.width,
                ).url
            if _get(story, "image_versions2"):
                story.image_url = max(
                    story.image_versions2.candidates,
                    key=lambda x: x.height * x.width,
                ).url
            stories.append(story)
        return [InstagramStory(**s) for s in stories]

    async def get_highlights(
        self, username: str, amount: Optional[int] = None
    ) -> list[InstagramHighlight]:
        user_id = (await self.get_user(username)).pk
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/highlights/{user_id}/highlights_tray/",
        )
        tray = list(_get(data, "tray", []) or [])
        if amount:
            tray = tray[:amount]
        highlights = []
        for highlight in tray:
            highlight.id = str(highlight.id).split(":")[-1]
            highlight.cover_media = highlight.cover_media.cropped_image_version.url
            highlights.append(highlight)
        return [InstagramHighlight(**h) for h in highlights]

    async def get_comments(self, url: str, amount: Optional[int] = None) -> list[InstagramComment]:
        post = await self.get_post(url)
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/media/{post[0].pk}/comments/",
        )
        comments = list(_get(data, "comments", []) or [])
        if amount:
            comments = comments[:amount]
        return [InstagramComment(**comment) for comment in comments]

    async def get_followers(
        self, username: str, amount: Optional[int] = None
    ) -> list[InstagramFollowerUser]:
        user = await self.get_user(username)
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/friendships/{user.pk}/followers/",
        )
        users = list(_get(data, "users", []) or [])
        followers = [InstagramFollowerUser(**f) for f in users]
        return followers[:amount] if amount else followers

    async def get_following(
        self, username: str, amount: Optional[int] = None
    ) -> list[InstagramFollowerUser]:
        user = await self.get_user(username)
        data = await self._request(
            "GET",
            f"https://i.instagram.com/api/v1/friendships/{user.pk}/following/",
        )
        users = list(_get(data, "users", []) or [])
        following = [InstagramFollowerUser(**f) for f in users]
        return following[:amount] if amount else following
