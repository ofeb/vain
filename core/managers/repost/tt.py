"""tiktok video downloader and repost.

Fetches a playable URL and sends the file only — no embed.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import BaseRepost

_URL_RE = re.compile(
    r"https?://(?:(?:www|m|vm|vt)\.)?tiktok\.com/\S+",
    re.I,
)


class TikTokRepost(BaseRepost):
    """repost handler for tiktok videos"""

    platform = "tiktok"

    async def fetch(self, url: str) -> Optional[dict]:
        """get tiktok video download url"""
        if not _URL_RE.search(url or "") and "tiktok.com" not in (url or "").lower():
            return None
        try:
            from core.networks.social.tiktok import TikTok

            client = TikTok()
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
                "save_count": post.save_count,
                "share_count": post.share_count,
                "music_title": post.music_title,
                "music_author": post.music_author,
                "music_url": post.music_url,
                "region": post.region,
                "source_url": post.url,
            }
        except Exception:
            return None
