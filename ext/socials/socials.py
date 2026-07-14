from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import textwrap
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.discord.package import Package

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from core.managers.values import color
from core.tools.aesthetic import aesthetic_embed, body

if TYPE_CHECKING:
    from core.vain import Vain

FONT_PATH = str(Path(__file__).resolve().parents[2] / "var" / "caption.otf")


def _ytdlp_download_sync(url: str, output_dir: str) -> dict:
    """Run yt-dlp synchronously to download media."""
    import yt_dlp

    opts = {
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return {}
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            for ext in (".mp4", ".webm", ".mkv", ".jpg", ".png"):
                if os.path.exists(base + ext):
                    filename = base + ext
                    break
        return {
            "filepath": filename,
            "filename": os.path.basename(filename),
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "thumbnail": info.get("thumbnail", ""),
        }


class Socials(Package):
    """Social media feeds and notifications."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
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
            await ctx.warn("Use `add` or `remove`.")

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
            await ctx.warn("Use `add` or `remove`.")

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
            await ctx.warn("Use `add` or `remove`.")

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
            await ctx.warn("Use `add` or `remove`.")

    @socials.command(
        name="list",
        description="View all configured social feeds",
        aliases=["all"],
    )
    @has_permissions(manage_guild=True)
    async def socials_list(self, ctx: Context) -> None:
        embed = aesthetic_embed(
            color=color.base,
            title="Social Feeds",
            message="No social feeds configured.",
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

        bio = data["bio"][:200] or "No bio"
        embed = aesthetic_embed(
            color=color.base,
            title=f"{data['full_name'] or data['username']} (@{data['username']})",
            message=bio,
        )
        embed.set_thumbnail(url=data["avatar"])
        embed.add_field(name="Followers", value=body(f"{data['followers']:,}"), inline=True)
        embed.add_field(name="Following", value=body(f"{data['following']:,}"), inline=True)
        embed.add_field(name="Posts", value=body(f"{data['posts']:,}"), inline=True)
        embed.add_field(name="Private", value=body("Yes" if data["is_private"] else "No"), inline=True)
        embed.add_field(name="Verified", value=body("Yes" if data["is_verified"] else "No"), inline=True)
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
        await ctx.invoke(self.tiktok_download, url=url)

    @tiktok.command(
        name="download",
        description="Download a TikTok video by URL",
        aliases=["dl", "get"],
    )
    async def tiktok_download(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                loop = asyncio.get_running_loop()
                with tempfile.TemporaryDirectory(prefix="tiktok-") as tmp:
                    result = await loop.run_in_executor(
                        None, _ytdlp_download_sync, url, tmp
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
                        await ctx.fail("File exceeds Discord's 25MB upload limit.")
                        return

                    with open(filepath, "rb") as f:
                        data = f.read()

                    filename = result.get("filename", "tiktok.mp4")
                    fp = io.BytesIO(data)
                    file = discord.File(fp, filename=filename)
                    await ctx.send(file=file)

            except Exception as e:
                await ctx.fail(f"Download failed: {str(e)[:200]}")

    @tiktok.command(
        name="info",
        description="Get information about a TikTok video",
        aliases=["details"],
    )
    async def tiktok_info(self, ctx: Context, *, url: str) -> None:
        embed = aesthetic_embed(
            color=color.base,
            title="TikTok Video",
            message=f"Info for `{url}`: requires API setup.",
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="repost",
        description="Repost media from TikTok, YouTube Shorts, Instagram, or Twitter",
        example=",repost https://www.tiktok.com/user/video/123",
        guilds=True,
        dms=False,
        groupchats=True,
    )
    @describe(url="Social media URL to repost")
    async def repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                loop = asyncio.get_running_loop()
                with tempfile.TemporaryDirectory(prefix="repost-") as tmp:
                    result = await loop.run_in_executor(
                        None, _ytdlp_download_sync, url, tmp
                    )
                    if not result or not result.get("filepath"):
                        await ctx.fail("Could not download media from that URL.")
                        return

                    filepath = result["filepath"]
                    if not os.path.exists(filepath):
                        await ctx.fail("Downloaded file not found.")
                        return

                    file_size = os.path.getsize(filepath)
                    if file_size > 25_000_000:
                        await ctx.fail("File exceeds Discord's 25MB upload limit.")
                        return

                    with open(filepath, "rb") as f:
                        data = f.read()

                    filename = result.get("filename", "repost.mp4")
                    fp = io.BytesIO(data)
                    file = discord.File(fp, filename=filename)
                    await ctx.send(file=file)

            except Exception as e:
                await ctx.fail(f"Download failed: {str(e)[:200]}")

    async def _generate_quote_image(
        self,
        content: str,
        display_name: str,
        username: str,
        avatar_url: str,
    ) -> bytes:
        """Generate a quote image locally using PIL."""
        loop = asyncio.get_running_loop()

        def _build() -> bytes:
            W, H = 857, 450
            font_size = 50

            try:
                font = ImageFont.truetype(FONT_PATH, font_size)
                name_font = ImageFont.truetype(FONT_PATH, 32)
                user_font = ImageFont.truetype(FONT_PATH, 22)
            except Exception:
                font = ImageFont.load_default()
                name_font = font
                user_font = font

            blank = Image.new("RGB", (W, H), color=(0, 0, 0))

            
            try:
                resp = urllib.request.urlopen(avatar_url)
                avatar_raw = resp.read()
                avatar = Image.open(io.BytesIO(avatar_raw)).convert("RGBA")
                avatar = avatar.resize((450, 450), Image.LANCZOS)
            except Exception:
                avatar = Image.new("RGBA", (450, 450), (80, 80, 80, 255))

            
            gradient = Image.new("RGBA", (450, 450), (0, 0, 0, 0))
            draw_grad = ImageDraw.Draw(gradient)
            for y in range(450):
                alpha = int(255 * (y / 450) * 0.7)
                draw_grad.line([(0, y), (450, y)], fill=(0, 0, 0, alpha))

            
            avatar.paste(Image.alpha_composite(avatar, gradient), (0, 0), avatar)
            avatar_rgb = avatar.convert("RGB")

            blank.paste(avatar_rgb, (0, 0))

            
            max_chars = 20
            words = content.split()
            lines = []
            current_line = ""
            for word in words:
                test = f"{current_line} {word}".strip()
                if len(test) <= max_chars:
                    current_line = test
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
            wrapped = "\n".join(lines)

            
            text_x = 550
            max_text_w = W - text_x - 30
            max_text_h = H - 120
            while font_size > 12:
                test_font = ImageFont.truetype(FONT_PATH, font_size)
                bbox = test_font.getbbox(wrapped)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                if tw <= max_text_w and th <= max_text_h:
                    font = test_font
                    break
                font_size -= 2

            
            draw = ImageDraw.Draw(blank)
            text_bbox = font.getbbox(wrapped)
            text_h = text_bbox[3] - text_bbox[1]
            text_y = (H - text_h) // 2 - 20
            draw.text((text_x, text_y), wrapped, fill=(255, 255, 255), font=font)

            
            name_y = text_y + text_h + 15
            draw.text((text_x, name_y), f"- {display_name}", fill=(255, 255, 255), font=name_font)

            
            user_y = name_y + 40
            draw.text((text_x, user_y), f"@{username}", fill=(89, 89, 89), font=user_font)

            
            draw.text((W - 100, H - 30), "vain", fill=(89, 89, 89), font=user_font)

            buf = io.BytesIO()
            blank.save(buf, format="PNG", quality=95)
            return buf.getvalue()

        return await loop.run_in_executor(None, _build)

    @hybrid(
        name="quote",
        description="Quote a message as an image",
        aliases=["qm", "quotemessage"],
    )
    @describe(message="Message to quote (or reply to one)")
    async def quote_command(self, ctx: Context, message: discord.Message = None) -> None:
        if not message and ctx.message.reference:
            message = ctx.message.reference.resolved
        if not message:
            return await ctx.warn("Please reply to a message to quote it.")
        if not message.content:
            return await ctx.warn("You cannot quote this message (no text content).")

        async with ctx.typing():
            avatar_url = str(message.author.display_avatar.url)
            image_data = await self._generate_quote_image(
                message.clean_content,
                message.author.display_name,
                message.author.name,
                avatar_url,
            )
            file = discord.File(io.BytesIO(image_data), filename="quote.png")
            await ctx.send(file=file)


async def setup(bot: Vain):
    await bot.add_cog(Socials(bot))
