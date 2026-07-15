"""Instagram fetch layer — i.instagram.com via core.api.Instagram."""

from __future__ import annotations

import logging
import re
from typing import Optional

from core.api import Error as ApiError
from core.api import Instagram as ApiInstagram

from .models import SocialPost

log = logging.getLogger("vain.social.instagram")

_IG_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/([\w-]+)",
    re.I,
)


def is_instagram_url(url: str) -> bool:
    u = (url or "").lower()
    return "instagram.com" in u or "instagr.am" in u


def shortcode_from_url(url: str) -> str | None:
    m = _IG_RE.search(url or "")
    return m.group(1) if m else None


class Instagram:
    """High-level Instagram client used by commands."""

    def __init__(self) -> None:
        self._api = ApiInstagram.from_config()

    async def close(self) -> None:
        return None

    async def post(self, url: str) -> Optional[SocialPost]:
        url = (url or "").strip()
        code = shortcode_from_url(url)
        clean = f"https://www.instagram.com/reel/{code}/" if code else url

        try:
            medias = await self._api.get_post(url)
        except ApiError as exc:
            log.debug("core.api ig post failed: %s", exc)
            medias = None
        except Exception as exc:
            log.debug("core.api ig error: %s", exc)
            medias = None

        if not medias:
            # Public oembed fallback for caption/author only
            return await self._from_oembed(clean, code or "")

        media = medias[0]
        user = media.user
        username = (user.username if user else None) or "unknown"
        display = (user.full_name if user else None) or username
        avatar = str(user.avatar) if user and user.avatar else None

        caption = ""
        if isinstance(media.caption, dict):
            caption = str(media.caption.get("text") or "")
        elif media.caption is not None and hasattr(media.caption, "text"):
            caption = str(getattr(media.caption, "text", "") or "")
        elif media.title:
            caption = str(media.title)

        media_urls: list[str] = []
        is_video = False
        if media.video_url:
            media_urls.append(str(media.video_url))
            is_video = True
        if media.image_urls:
            media_urls.extend(str(u) for u in media.image_urls if u)
        if not media_urls and media.thumbnail_url:
            media_urls.append(str(media.thumbnail_url))

        return SocialPost(
            platform="instagram",
            url=clean,
            username=str(username).lstrip("@"),
            display_name=str(display),
            avatar_url=avatar,
            caption=caption[:2000],
            media_urls=media_urls,
            is_video=is_video,
            like_count=int(media.like_count or 0),
            comment_count=int(media.comment_count or 0),
            play_count=int(media.play_count or 0),
            raw={},
        )

    async def profile(self, username: str) -> Optional[dict]:
        try:
            user = await self._api.get_user(username)
            return user.model_dump()
        except Exception as exc:
            log.debug("ig profile failed: %s", exc)
            return None

    async def _from_oembed(self, url: str, code: str) -> Optional[SocialPost]:
        import aiohttp

        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-IG-App-ID": "936619743392459",
            "Accept": "*/*",
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    f"https://www.instagram.com/api/v1/oembed/?url={url}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)
        except Exception as exc:
            log.debug("ig oembed failed: %s", exc)
            return None
        if not isinstance(data, dict):
            return None
        author = data.get("author_name") or "unknown"
        thumb = data.get("thumbnail_url")
        return SocialPost(
            platform="instagram",
            url=url,
            username=str(author).lstrip("@"),
            display_name=str(author),
            avatar_url=thumb,
            caption=str(data.get("title") or "")[:2000],
            media_urls=[thumb] if thumb else [],
            is_video=False,
            raw=data,
        )
