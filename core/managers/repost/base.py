"""base class for media repost handlers.
provides download and send logic all platforms share.
subclass this and implement fetch"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import aiohttp
import discord
from discord.ext.commands import Context

if TYPE_CHECKING:
    from core.vain import Vain


class BaseRepost:
    """abstract base for platform repost handlers"""

    platform: str = "unknown"

    def __init__(self, bot: Vain):
        self.bot = bot

    async def fetch(self, url: str) -> Optional[dict]:
        """fetch media info from url, return dict with video/audio url"""
        raise NotImplementedError

    async def send(self, ctx: Context, url: str) -> Optional[discord.Message]:
        """download and send media from url to channel (file only, no embed)"""
        data = await self.fetch(url)
        if not data:
            await ctx.fail(f"couldnt get media from {self.platform}")
            return None
        media_url = data.get("url") or data.get("video_url") or data.get("audio_url")
        if not media_url:
            await ctx.fail(f"no media found for that {self.platform} url")
            return None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": (
                "https://www.instagram.com/"
                if self.platform == "instagram"
                else "https://www.tiktok.com/"
            ),
        }
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(media_url) as r:
                if r.status != 200:
                    await ctx.fail("couldnt download the media")
                    return None
                content_type = (r.content_type or "").lower()
                if data.get("is_video") or "video" in content_type or str(media_url).lower().endswith(".mp4"):
                    ext = "mp4"
                elif "audio" in content_type:
                    ext = "mp3"
                elif "image" in content_type or "jpeg" in content_type:
                    ext = "jpg"
                else:
                    ext = "mp4"
                data_bytes = await r.read()
                if len(data_bytes) > 25_000_000:
                    await ctx.fail("file exceeds Discord's 25MB upload limit")
                    return None
        file = discord.File(
            fp=__import__("io").BytesIO(data_bytes),
            filename=f"{self.platform}.{ext}",
        )
        # plain file — no embed, no components
        return await ctx.send(file=file)
