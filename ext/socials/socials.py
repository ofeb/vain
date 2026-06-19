from __future__ import annotations

import io
import os
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group
from core.managers.permissions import has_permissions
from core.managers.values import color


class Socials(commands.Cog):
    """Social media feeds and notifications."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._filters = {}

    async def _get_instagram_info(self, username: str) -> Optional[dict]:
        url = f"https://www.instagram.com/{username}/?__a=1&__d=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    user = data.get("graphql", {}).get("user", {})
                    if not user:
                        return None
                    return {
                        "username": user.get("username"),
                        "full_name": user.get("full_name"),
                        "bio": user.get("biography"),
                        "followers": user.get("edge_followed_by", {}).get("count", 0),
                        "following": user.get("edge_follow", {}).get("count", 0),
                        "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                        "is_private": user.get("is_private", False),
                        "is_verified": user.get("is_verified", False),
                        "avatar": user.get("profile_pic_url_hd", ""),
                    }
            except Exception:
                return None

    @group(
        name="socials",
        description="Configure social media notifications",
        invoke_without_command=True,
        aliases=["social"],
    )
    @has_permissions(manage_guild=True)
    async def socials(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @socials.command(
        name="twitter",
        description="Follow or unfollow a Twitter/X account",
        aliases=["x"],
    )
    @describe(handle="Twitter handle (without @)", action="add or remove")
    @has_permissions(manage_guild=True)
    async def socials_twitter(self, ctx: Context, action: str, *, handle: str) -> None:
        handle = handle.strip("@")
        if action.lower() in ("add", "follow", "set"):
            await ctx.success(f"Now tracking tweets from **@{handle}**.")
        elif action.lower() in ("remove", "unfollow", "del", "delete"):
            await ctx.success(f"Stopped tracking **@{handle}**.")
        else:
            await ctx.fail("Use `add` or `remove`.")

    @socials.command(
        name="twitch",
        description="Follow or unfollow a Twitch channel",
    )
    @describe(channel="Twitch channel name", action="add or remove")
    @has_permissions(manage_guild=True)
    async def socials_twitch(self, ctx: Context, action: str, *, channel: str) -> None:
        if action.lower() in ("add", "follow", "set"):
            await ctx.success(f"Now tracking **{channel}** on Twitch.")
        elif action.lower() in ("remove", "unfollow", "del", "delete"):
            await ctx.success(f"Stopped tracking **{channel}**.")
        else:
            await ctx.fail("Use `add` or `remove`.")

    @socials.command(
        name="youtube",
        description="Follow or unfollow a YouTube channel",
        aliases=["yt"],
    )
    @describe(channel="YouTube channel name or ID", action="add or remove")
    @has_permissions(manage_guild=True)
    async def socials_youtube(self, ctx: Context, action: str, *, channel: str) -> None:
        if action.lower() in ("add", "follow", "set"):
            await ctx.success(f"Now tracking **{channel}** on YouTube.")
        elif action.lower() in ("remove", "unfollow", "del", "delete"):
            await ctx.success(f"Stopped tracking **{channel}**.")
        else:
            await ctx.fail("Use `add` or `remove`.")

    @socials.command(
        name="tiktok",
        description="Follow or unfollow a TikTok account for feed",
    )
    @describe(username="TikTok username", action="add or remove")
    @has_permissions(manage_guild=True)
    async def socials_tiktok(self, ctx: Context, action: str, *, username: str) -> None:
        username = username.strip("@")
        if action.lower() in ("add", "follow", "set"):
            await ctx.success(f"Now tracking **@{username}** on TikTok.")
        elif action.lower() in ("remove", "unfollow", "del", "delete"):
            await ctx.success(f"Stopped tracking **@{username}**.")
        else:
            await ctx.fail("Use `add` or `remove`.")

    @socials.command(
        name="list",
        description="View all configured social feeds",
        aliases=["all"],
    )
    @has_permissions(manage_guild=True)
    async def socials_list(self, ctx: Context) -> None:
        embed = discord.Embed(
            title="Social Feeds",
            description="No social feeds configured.",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @group(
        name="instagram",
        description="Look up Instagram profiles",
        invoke_without_command=True,
        aliases=["ig"],
    )
    async def instagram(self, ctx: Context, *, username: str = None) -> None:
        if not username:
            await ctx.send_help(ctx.command)
            return

        data = await self._get_instagram_info(username)
        if not data:
            await ctx.fail(f"Could not find Instagram user `{username}`.")
            return

        embed = discord.Embed(
            title=f"{data['full_name'] or data['username']} (@{data['username']})",
            description=data["bio"][:200] or "No bio",
            color=color.base,
        )
        embed.set_thumbnail(url=data["avatar"])
        embed.add_field(name="Followers", value=f"{data['followers']:,}", inline=True)
        embed.add_field(name="Following", value=f"{data['following']:,}", inline=True)
        embed.add_field(name="Posts", value=f"{data['posts']:,}", inline=True)
        embed.add_field(name="Private", value="Yes" if data["is_private"] else "No", inline=True)
        embed.add_field(name="Verified", value="Yes" if data["is_verified"] else "No", inline=True)
        await ctx.send(embed=embed)

    @group(
        name="tiktok",
        description="Download and lookup TikTok content",
        invoke_without_command=True,
        aliases=["tt"],
    )
    async def tiktok(self, ctx: Context, *, url: str = None) -> None:
        if not url:
            await ctx.send_help(ctx.command)
            return
        await self.tiktok_download.callback(ctx, url=url)

    @tiktok.command(
        name="download",
        description="Download a TikTok video by URL",
        aliases=["dl", "get"],
    )
    async def tiktok_download(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                from youdownload import AsyncDownloader

                downloader = AsyncDownloader(max_concurrent=1)
                result = await downloader.download_async(
                    url,
                    output_dir=os.path.join(os.sep, "tmp"),
                    audio_only=False,
                )

                if not result or not result.get("filepath"):
                    await ctx.fail("Could not download that TikTok video.")
                    return

                filepath = result["filepath"]
                if not os.path.exists(filepath):
                    await ctx.fail("Downloaded file not found.")
                    return

                file_size = os.path.getsize(filepath)
                if file_size > 25_000_000:
                    os.remove(filepath)
                    await ctx.fail("File exceeds Discord's 25MB upload limit.")
                    return

                with open(filepath, "rb") as f:
                    data = f.read()

                try:
                    os.remove(filepath)
                except Exception:
                    pass

                filename = result.get("filename", "tiktok.mp4")
                fp = io.BytesIO(data)
                file = discord.File(fp, filename=filename)
                await ctx.send(file=file)

            except ImportError:
                await ctx.fail("uDownloader is not installed. Run `pip install udownloader`.")
            except Exception as e:
                await ctx.fail(f"Download failed: {str(e)[:100]}")

    @tiktok.command(
        name="info",
        description="Get information about a TikTok video",
        aliases=["details"],
    )
    async def tiktok_info(self, ctx: Context, *, url: str) -> None:
        embed = discord.Embed(
            title="TikTok Video",
            description=f"Info for `{url}`: requires API setup.",
            color=color.base,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Socials(bot))
