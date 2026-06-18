"""tiktok video downloader and repost.
fetches tiktok video without watermark via api.
use TikTokRepost.send in commands"""

import re, aiohttp
from .base import BaseRepost
from typing import Optional

_URL_RE = re.compile(r"https?://(www\.)?tiktok\.com/.+")


class TikTokRepost(BaseRepost):
    """repost handler for tiktok videos"""

    platform = "tiktok"

    async def fetch(self, url: str) -> Optional[dict]:
        """get tiktok video download url"""
        if not _URL_RE.match(url):
            return None
        api = f"https://api.tiklydown.eu.org/api/download/v3?url={url}"
        async with aiohttp.ClientSession() as s:
            async with s.get(api) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return {"url": data.get("video", {}).get("noWatermark")}
