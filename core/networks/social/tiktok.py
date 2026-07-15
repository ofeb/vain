"""TikTok fetch layer: udownloader first, then core.api.TikTok fallback."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import unquote

from core.api import Error as ApiError
from core.api import TikTok as ApiTikTok
from core.api import UDownloader

from .models import SocialPost

log = logging.getLogger("vain.social.tiktok")

_TT_HOSTS = re.compile(
    r"(?:https?://)?(?:(?:www|m|vm|vt)\.)?(?:tiktok\.com|tiktokv\.com)",
    re.I,
)
_VIDEO_ID_RE = re.compile(r"/video/(\d+)")
_USER_RE = re.compile(r"tiktok\.com/@([^/?#]+)", re.I)


def is_tiktok_url(url: str) -> bool:
    u = url or ""
    return bool(_TT_HOSTS.search(u)) or "vm.tiktok" in u or "vt.tiktok" in u


class TikTok:
    """High-level TikTok client used by commands."""

    def __init__(self) -> None:
        self._downloader = UDownloader()
        self._api = ApiTikTok()

    async def close(self) -> None:
        return None

    async def post(self, url: str) -> Optional[SocialPost]:
        url = (url or "").strip()
        if not url:
            return None

        # 1) udownloader (yt-dlp extract) — playable URL + basic meta
        post = await self._from_udownloader(url)

        # 2) core.api rehydration scrape — richer meta + playAddr
        api_post = await self._from_core_api(url)
        if api_post:
            post = self._merge(post, api_post) if post else api_post

        if not post:
            return None
        if not post.display_name:
            post.display_name = post.username
        return post

    async def user(self, username: str) -> Optional[dict]:
        username = (username or "").lstrip("@").strip()
        try:
            u = await self._api.get_user(username)
            return u.model_dump()
        except Exception as exc:
            log.debug("tiktok user failed: %s", exc)
            return None

    async def info(self, url: str) -> Optional[dict]:
        post = await self.post(url)
        return post.__dict__ if post else None

    async def _from_udownloader(self, url: str) -> Optional[SocialPost]:
        try:
            result = await self._downloader.extract(url)
        except Exception as exc:
            log.debug("udownloader failed: %s", exc)
            return None
        if not result or not result.play_url:
            return None
        username = (result.uploader_id or result.uploader or "unknown").lstrip("@")
        um = _USER_RE.search(result.webpage_url or url)
        if um:
            username = unquote(um.group(1))
        return SocialPost(
            platform="tiktok",
            url=result.webpage_url or url,
            username=username or "unknown",
            display_name=result.uploader or username,
            avatar_url=result.thumbnail,
            caption=result.description or result.title,
            media_urls=[result.play_url],
            is_video=True,
            like_count=result.like_count,
            comment_count=result.comment_count,
            share_count=result.repost_count,
            play_count=result.view_count,
            raw=result.raw,
        )

    async def _from_core_api(self, url: str) -> Optional[SocialPost]:
        try:
            video = await self._api.get_video(url)
        except ApiError as exc:
            log.debug("core.api tiktok failed: %s", exc)
            return None
        except Exception as exc:
            log.debug("core.api tiktok error: %s", exc)
            return None

        author = video.author
        username = (author.username if author else "") or "unknown"
        display = (author.nickname if author else "") or username
        avatar = None
        if author and author.avatar:
            avatar = str(author.avatar)

        stats = video.stats
        music = video.music
        music_title = music.title if music else None
        music_author = music.author if music else None
        music_id = music.id if music else None
        music_url = (
            f"https://www.tiktok.com/music/original-sound-{music_id}"
            if music_id
            else None
        )

        media: list[str] = []
        if video.url:
            media.append(str(video.url))

        return SocialPost(
            platform="tiktok",
            url=video.webpage_url or url,
            username=str(username).lstrip("@"),
            display_name=str(display),
            avatar_url=avatar,
            caption=video.description or "",
            media_urls=media,
            is_video=True,
            like_count=int(stats.likes) if stats else 0,
            comment_count=int(stats.comments) if stats else 0,
            share_count=int(stats.shares) if stats else 0,
            save_count=int(stats.saves) if stats else 0,
            play_count=int(stats.plays) if stats else 0,
            music_title=music_title,
            music_author=music_author,
            music_url=music_url,
            region=video.region,
            raw={},
        )

    @staticmethod
    def _merge(base: SocialPost, extra: SocialPost) -> SocialPost:
        # Prefer CDN play URL from either side
        if extra.media_urls and (
            not base.media_urls
            or any("tiktokcdn" in u or "playAddr" in u or ".mp4" in u for u in extra.media_urls)
        ):
            # Keep existing if already good CDN
            if not any("tiktokcdn" in (u or "") or "mime_type=video" in (u or "") for u in base.media_urls):
                base.media_urls = extra.media_urls
        if base.username in ("", "unknown") and extra.username not in ("", "unknown"):
            base.username = extra.username
            base.display_name = extra.display_name or base.display_name
        if not base.avatar_url and extra.avatar_url:
            base.avatar_url = extra.avatar_url
        if len(extra.caption or "") > len(base.caption or ""):
            base.caption = extra.caption
        for attr in ("like_count", "comment_count", "share_count", "save_count", "play_count"):
            if not getattr(base, attr) and getattr(extra, attr):
                setattr(base, attr, getattr(extra, attr))
        if not base.music_title and extra.music_title:
            base.music_title = extra.music_title
            base.music_author = extra.music_author
            base.music_url = extra.music_url
        if not base.region and extra.region:
            base.region = extra.region
        if extra.url and ("tiktok.com/@" in extra.url or "/video/" in extra.url):
            base.url = extra.url
        return base
