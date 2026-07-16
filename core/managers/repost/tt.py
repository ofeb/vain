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
            return {"url": post.media_urls[0], "is_video": True}
        except Exception:
            return None
