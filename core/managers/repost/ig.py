"""instagram reel and post repost handler.
fetches public instagram media via instaloader style api.
use IGRepost.send in commands"""

import re, aiohttp
from .base import BaseRepost
from typing import Optional

_URL_RE = re.compile(r"https?://(www\.)?instagram\.com/(p|reel)/[\w-]+")


class IGRepost(BaseRepost):
    """repost handler for instagram posts"""

    platform = "instagram"

    async def fetch(self, url: str) -> Optional[dict]:
        """get instagram media url"""
        if not _URL_RE.match(url):
            return None
        shortcode = url.rstrip("/").split("/")[-1]
        api = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(api) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        media = data.get("graphql", {}).get("shortcode_media", {})
        return {"url": media.get("video_url") or media.get("display_url")}
