"""base class for media repost handlers.
provides download and send logic all platforms share.
subclass this and implement fetch"""

from __future__ import annotations

import io
from typing import Optional, TYPE_CHECKING

import aiohttp
import discord
from discord.ext.commands import Context

from core.networks.media.compress import discord_upload_limit, fit_for_discord

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
            async with s.get(media_url, timeout=aiohttp.ClientTimeout(total=60)) as r:
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
                if not data_bytes:
                    await ctx.fail("couldnt download the media")
                    return None
                if len(data_bytes) > 100 * 1024 * 1024:
                    await ctx.fail("file is too large to process")
                    return None

        limit = discord_upload_limit(getattr(ctx, "guild", None))
        fitted, name = await fit_for_discord(
            data_bytes,
            filename=f"{self.platform}.{ext}",
            guild=getattr(ctx, "guild", None),
            max_bytes=limit,
        )
        if len(fitted) > limit:
            await ctx.fail(
                f"file exceeds Discord's upload limit even after compression "
                f"({len(fitted) / (1024 * 1024):.1f}MB)."
            )
            return None

        file = discord.File(fp=io.BytesIO(fitted), filename=name)
        try:
            return await ctx.send(file=file)
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 40005 or exc.status == 413:
                tighter = max(8 * 1024 * 1024, limit // 2)
                fitted2, name2 = await fit_for_discord(
                    fitted, filename=name, max_bytes=tighter
                )
                if len(fitted2) > tighter:
                    await ctx.fail("file is too large for Discord even after compression")
                    return None
                return await ctx.send(file=discord.File(io.BytesIO(fitted2), filename=name2))
            raise
