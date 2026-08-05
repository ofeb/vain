"""youtube video download and repost handler.
uses yt-dlp to get best audio or video stream.
use YTRepost.send in commands"""

import asyncio
from .base import BaseRepost
from typing import Optional


class YTRepost(BaseRepost):
    """repost handler for youtube videos"""

    platform = "youtube"

    async def fetch(self, url: str) -> Optional[dict]:
        """get youtube media url via yt-dlp"""
        try:
            import yt_dlp
        except ImportError:
            return None
        opts = {"format": "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best", "quiet": True}
        loop = asyncio.get_event_loop()
        def _extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        info = await loop.run_in_executor(None, _extract)
        return {"url": info.get("url"), "title": info.get("title")}
