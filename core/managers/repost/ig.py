"""instagram reel and post repost handler.

Uses vain.rest public API (no session cookies).
Sends the video/image file only — no embed.
"""

from __future__ import annotations

import re
from typing import Optional

from core.api.vain_rest import VainRest
from .base import BaseRepost

_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/[\w-]+",
    re.I,
)


class IGRepost(BaseRepost):
    """repost handler for instagram posts"""

    platform = "instagram"

    async def fetch(self, url: str) -> Optional[dict]:
        """get instagram media url via vain.rest"""
        if not _URL_RE.search(url or ""):
            return None
        try:
            client = VainRest()
            video = await client.instagram_get_video_url(url)
            if video:
                return {"url": video, "is_video": True}
            medias = await client.instagram_get_post(url)
            if not medias:
                return None
            
            image_urls: list[str] = []
            video_url: str | None = None
            for media in medias:
                if media.get("video_url") and not video_url:
                    video_url = str(media["video_url"])
                for img in media.get("image_urls") or []:
                    if img and str(img) not in image_urls:
                        image_urls.append(str(img))
                thumb = media.get("thumbnail_url")
                if thumb and str(thumb) not in image_urls:
                    image_urls.append(str(thumb))
            if video_url:
                return {"url": video_url, "is_video": True, "media_urls": [video_url] + image_urls}
            if image_urls:
                return {
                    "url": image_urls[0],
                    "is_video": False,
                    "media_urls": image_urls,
                }
        except Exception:
            return None
        return None
