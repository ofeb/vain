"""instagram reel and post repost handler.

Uses vainapi public download APIs (no session cookies).
Sends the video/image file only — no embed.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import BaseRepost

_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/[\w-]+",
    re.I,
)


class IGRepost(BaseRepost):
    """repost handler for instagram posts"""

    platform = "instagram"

    async def fetch(self, url: str) -> Optional[dict]:
        """get instagram media url via vainapi (cookie-free)"""
        if not _URL_RE.search(url or ""):
            return None
        try:
            from core.api.internal.instagram import Instagram

            client = Instagram()
            video = await client.get_video_url(url)
            if video:
                return {"url": video, "is_video": True}
            medias = await client.get_post(url)
            if not medias:
                return None
            media = medias[0]
            if media.video_url:
                return {"url": str(media.video_url), "is_video": True}
            if media.image_urls:
                return {"url": str(media.image_urls[0]), "is_video": False}
            if media.thumbnail_url:
                return {"url": str(media.thumbnail_url), "is_video": False}
        except Exception:
            return None
        return None
