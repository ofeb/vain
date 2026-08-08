"""instagram reel and post repost handler.

Uses social API primary (vain.rest fallback).
Sends the video/image file only - no embed.
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
        """get instagram media url via social network client"""
        if not _URL_RE.search(url or ""):
            return None
        try:
            from core.networks.social.ig import Instagram

            client = Instagram()
            try:
                post = await client.post(url)
            finally:
                await client.close()
            if not post or not post.media_urls:
                return None
            return {
                "url": post.media_urls[0],
                "is_video": bool(post.is_video),
                "media_urls": list(post.media_urls),
                "username": post.username,
                "display_name": post.display_name,
                "caption": post.caption,
                "avatar_url": post.avatar_url,
                "like_count": post.like_count,
                "comment_count": post.comment_count,
                "source_url": post.url,
            }
        except Exception:
            return None
