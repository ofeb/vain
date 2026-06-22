from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bleed import Bleed


from typing import Optional

import aiohttp
import discord
from discord.ext import commands

from core.discord.package import Package

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.values import color

SC_API_URL = "https://api-v2.soundcloud.com"
DEFAULT_CLIENT_ID = "a3e059563d7fd3372b49b37f00a00bcf"


class Soundcloud(Package):
    """SoundCloud track lookup and playback."""


    async def _resolve(self, url: str) -> Optional[dict]:
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {"url": url, "client_id": DEFAULT_CLIENT_ID}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{SC_API_URL}/resolve", headers=headers, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            except Exception:
                return None

    async def _search(self, query: str, limit: int = 5) -> list[dict]:
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {
            "q": query,
            "client_id": DEFAULT_CLIENT_ID,
            "limit": limit,
            "type": "track",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{SC_API_URL}/search/tracks", headers=headers, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("collection", [])
            except Exception:
                return []

    def _format_duration(self, ms: int) -> str:
        seconds = ms // 1000
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{sec:02d}"
        return f"{minutes}:{sec:02d}"

    @group(
        name="soundcloud",
        description="Search and play SoundCloud tracks",
        invoke_without_command=True,
        aliases=["sc"],
    )
    async def soundcloud(self, ctx: Context, *, query: str) -> None:
        results = await self._search(query)
        if not results:
            await ctx.fail(f"No results found for `{query}`.")
            return

        entries = []
        for i, track in enumerate(results[:5], 1):
            duration = self._format_duration(track.get("duration", 0))
            entries.append(f"`{i}.` **{track['title']}** — {track['user']['username']} ({duration})")

        embed = discord.Embed(
            title=f"SoundCloud Search — {query}",
            description="\n".join(entries),
            color=color.base,
        )
        embed.set_footer(text="Powered by SoundCloud API")
        await ctx.send(embed=embed)

    @soundcloud.command(
        name="search",
        description="Search for a track on SoundCloud",
    )
    @describe(query="Search query")
    async def soundcloud_search(self, ctx: Context, *, query: str) -> None:
        await self.soundcloud.callback(ctx, query=query)

    @soundcloud.command(
        name="info",
        description="Get information about a SoundCloud track",
    )
    @describe(url="SoundCloud track URL")
    async def soundcloud_info(self, ctx: Context, url: str) -> None:
        data = await self._resolve(url)
        if not data:
            await ctx.fail("Could not retrieve track info.")
            return

        embed = discord.Embed(
            title=data.get("title", "Unknown Track"),
            description=data.get("description", "")[:200] or "No description",
            color=color.base,
        )
        embed.set_author(name=data["user"]["username"], url=data["user"].get("permalink_url"))
        embed.add_field(name="Duration", value=self._format_duration(data.get("duration", 0)), inline=True)
        embed.add_field(name="Plays", value=f"{data.get('playback_count', 0):,}", inline=True)
        embed.add_field(name="Likes", value=f"{data.get('favoritings_count', 0):,}", inline=True)
        embed.add_field(name="Comments", value=data.get("comment_count", 0), inline=True)
        if data.get("artwork_url"):
            embed.set_thumbnail(url=data["artwork_url"].replace("large", "t500x500"))
        await ctx.send(embed=embed)


async def setup(bot: Bleed):
    await bot.add_cog(Soundcloud(bot))
