﻿"""base class for media repost handlers.
provides download and send logic all platforms share.
subclass this and implement fetch"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import aiohttp
import discord
from discord.ext.commands import Context

if TYPE_CHECKING:
    from core.bleed import Bleed


class BaseRepost:
    """abstract base for platform repost handlers"""

    platform: str = "unknown"

    def __init__(self, bot: Bleed):
        self.bot = bot

    async def fetch(self, url: str) -> Optional[dict]:
        """fetch media info from url, return dict with video/audio url"""
        raise NotImplementedError

    async def send(self, ctx: Context, url: str) -> Optional[discord.Message]:
        """download and send media from url to channel"""
        data = await self.fetch(url)
        if not data:
            await ctx.fail(f"couldnt get media from {self.platform}")
            return None
        media_url = data.get("url") or data.get("video_url") or data.get("audio_url")
        if not media_url:
            await ctx.fail(f"no media found for that {self.platform} url")
            return None
        async with aiohttp.ClientSession() as s:
            async with s.get(media_url) as r:
                if r.status != 200:
                    await ctx.fail("couldnt download the media")
                    return None
                content_type = r.content_type
                ext = "mp4" if "video" in content_type else "mp3" if "audio" in content_type else "bin"
                data_bytes = await r.read()
        file = discord.File(fp=__import__("io").BytesIO(data_bytes), filename=f"media.{ext}")
        return await ctx.reply(file=file)
