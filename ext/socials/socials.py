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
from core.tools.aesthetic import (
    aesthetic_embed,
    body,
    build_social_repost_container,
    get_bot_dominant_color,
)
from core.networks.social import Instagram, TikTok, is_instagram_url, is_tiktok_url
from core.networks.social.models import SocialPost

if TYPE_CHECKING:
    from core.vain import Vain

FONT_PATH = str(Path(__file__).resolve().parents[2] / "var" / "caption.otf")


def _ytdlp_download_sync(url: str, output_dir: str) -> dict:
    """Run yt-dlp synchronously to download media."""
    import yt_dlp

    opts: dict = {
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    # Instagram often needs session cookies for reels
    try:
        from core.managers.values import api as api_cfg

        cookie = api_cfg.instagram.cookie_header()
        if cookie and ("instagram.com" in (url or "") or "instagr.am" in (url or "")):
            opts["http_headers"] = {
                "Cookie": cookie,
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                    "Instagram 192.0.0.37.107"
                ),
                "X-IG-App-ID": "936619743392459",
            }
    except Exception:
        pass

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
        client = TikTok()
        try:
            post = await client.post(url)
        finally:
            await client.close()
        if not post:
            await ctx.fail("Could not fetch that TikTok.")
            return
        lines = [
            f"**Author:** [{post.display_name}]({post.profile_url}) (@{post.username})",
            f"**Likes:** `{post.like_count:,}` · **Comments:** `{post.comment_count:,}`",
            f"**Shares:** `{post.share_count:,}` · **Saves:** `{post.save_count:,}`",
        ]
        if post.music_title:
            lines.append(f"**Music:** {post.music_title}")
        if post.caption:
            lines.append(f"**Caption:** {post.caption[:300]}")
        embed = aesthetic_embed(
            color=color.base,
            title="TikTok Video",
            message="\n".join(lines),
        )
        if post.avatar_url:
            embed.set_thumbnail(url=post.avatar_url)
        await ctx.send(embed=embed)

    @hybrid(
        name="repost",
        description="Repost Instagram / TikTok as a clean V2 container",
        example=",repost https://www.instagram.com/reel/xxxx",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(url="Social media post URL")
    async def repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")

    async def _resolve_embed_color(self, ctx: Context) -> int:
        """Prefer custom base color, else bot dominant, else fallback."""
        try:
            custom = await self.bot.db.get_color(
                ctx.guild.id if ctx.guild else 0,
                ctx.author.id if ctx.guild else None,
            )
            base = custom.get("base")
            if isinstance(base, int) and base:
                return base
        except Exception:
            pass
        try:
            return await get_bot_dominant_color(ctx.bot)
        except Exception:
            return getattr(ctx.bot, "color", None) or color.base or 0x2A2B2F

    @staticmethod
    def _is_video_url(u: str) -> bool:
        lu = (u or "").lower()
        return any(
            token in lu
            for token in (
                ".mp4",
                "mime_type=video",
                "/video/",
                "video_mp4",
                "playwm",
                "play?",
                "aweme",
                "/v/t16/",
                "/v/t50/",
            )
        )

    async def _download_bytes(self, media_url: str) -> bytes | None:
        try:
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0"}
            ) as session:
                async with session.get(
                    media_url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
                    if len(data) > 25_000_000:
                        return None
                    return data
        except Exception:
            return None

    async def _ytdlp_file(self, source_url: str, platform: str) -> discord.File | None:
        """Download playable media via yt-dlp (needed for IG reels without public CDN)."""
        loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory(prefix="repost-") as tmp:
            result = await loop.run_in_executor(None, _ytdlp_download_sync, source_url, tmp)
            if not result or not result.get("filepath"):
                return None
            filepath = result["filepath"]
            if not os.path.exists(filepath) or os.path.getsize(filepath) > 25_000_000:
                return None
            with open(filepath, "rb") as fh:
                data = fh.read()
            ext = os.path.splitext(result.get("filename") or "media.mp4")[1] or ".mp4"
            return discord.File(io.BytesIO(data), filename=f"{platform}{ext}")

    async def _repost(self, ctx: Context, url: str) -> None:
        url = (url or "").strip()
        if not url:
            await ctx.warn("Provide a TikTok or Instagram URL.")
            return

        accent = await self._resolve_embed_color(ctx)

        post: SocialPost | None = None
        if is_tiktok_url(url) or "vm.tiktok" in url or "vt.tiktok" in url:
            client = TikTok()
            try:
                post = await client.post(url)
            finally:
                await client.close()
        elif is_instagram_url(url):
            client = Instagram()
            try:
                post = await client.post(url)
            finally:
                await client.close()
        else:
            await ctx.warn("Only **TikTok** and **Instagram** links are supported.")
            return

        if post is None:
            await ctx.fail("Could not fetch that post. It may be private or unavailable.")
            return

        media_urls = [u for u in (post.media_urls or []) if u]
        video_urls = [u for u in media_urls if self._is_video_url(u)]
        image_urls = [u for u in media_urls if not self._is_video_url(u)]

        gallery_urls: list[str] = []
        upload: discord.File | None = None
        component_file: discord.File | None = None

        # Prefer CDN video in MediaGallery (heist-style). Download when needed.
        if video_urls:
            # Discord can proxy many CDN mp4s in MediaGallery
            gallery_urls = video_urls[:1]
            # Also try to attach downloaded file for reliability
            data = await self._download_bytes(video_urls[0])
            if data:
                upload = discord.File(io.BytesIO(data), filename=f"{post.platform}.mp4")
                component_file = discord.File(io.BytesIO(data), filename=f"{post.platform}.mp4")
                gallery_urls = []  # use File component instead of remote URL
        elif post.is_video or "/reel" in (post.url or url).lower():
            # Reel/video post but no public CDN URL (common for IG without cookies)
            f = await self._ytdlp_file(post.url or url, post.platform)
            if f:
                # Need two File objects for upload + component ref
                # Re-download once more via ytdlp is wasteful — re-read from f buffer
                f.fp.seek(0)
                raw = f.fp.read()
                upload = discord.File(io.BytesIO(raw), filename=f.filename)
                component_file = discord.File(io.BytesIO(raw), filename=f.filename)
            else:
                await ctx.fail(
                    "Could not download that video. Instagram often requires cookies "
                    "for reels — set `api.instagram` session cookies in values."
                )
                return
        elif image_urls:
            gallery_urls = image_urls[:4]
        else:
            f = await self._ytdlp_file(post.url or url, post.platform)
            if f:
                f.fp.seek(0)
                raw = f.fp.read()
                upload = discord.File(io.BytesIO(raw), filename=f.filename)
                component_file = discord.File(io.BytesIO(raw), filename=f.filename)
            else:
                await ctx.fail("Could not get media for that post.")
                return

        comps = build_social_repost_container(
            platform=post.platform,
            username=post.username,
            display_name=post.display_name or post.username,
            caption=post.caption,
            media_urls=gallery_urls,
            avatar_url=post.avatar_url,
            source_url=post.url or url,
            accent=accent,
            like_count=post.like_count,
            comment_count=post.comment_count,
            save_count=post.save_count,
            share_count=post.share_count,
            region=post.region,
            music_title=post.music_title,
            music_author=post.music_author,
            music_url=post.music_url,
            attachment=component_file,
        )

        if upload is not None:
            await ctx.send(components=comps, file=upload)
        else:
            await ctx.send(components=comps)

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





class EmbedBuilderModal(discord.ui.Modal, title="Edit Embed Part"):
    def __init__(self, key: str, current: str = ""):
        super().__init__()
        self.key = key
        self.input = discord.ui.TextInput(
            label=key.title(),
            style=discord.TextStyle.paragraph if key in ("description", "fields") else discord.TextStyle.short,
            default=current[:100] if current else "",
            required=False,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        self.value = self.input.value
        await interaction.response.defer()

class EmbedBuilderView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.data = {"title": "", "description": "", "color": "2b2d31", "image": "", "thumbnail": ""}
        self.message: discord.Message | None = None

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        return inter.user.id == self.author_id

    @discord.ui.select(
        placeholder="Choose what to edit...",
        options=[
            discord.SelectOption(label="Title", value="title"),
            discord.SelectOption(label="Description", value="description"),
            discord.SelectOption(label="Color (hex)", value="color"),
            discord.SelectOption(label="Image URL", value="image"),
            discord.SelectOption(label="Thumbnail URL", value="thumbnail"),
        ]
    )
    async def choose(self, inter: discord.Interaction, select: discord.ui.Select):
        key = select.values[0]
        modal = EmbedBuilderModal(key, self.data.get(key, ""))
        await inter.response.send_modal(modal)
        await modal.wait()
        if hasattr(modal, "value"):
            self.data[key] = modal.value or ""
        
        if self.message:
            await self._update_preview(inter)

    async def _update_preview(self, inter: discord.Interaction):
        script = self._to_script()
        try:
            await self.message.edit(content=f"```yaml\n{script}\n```")
        except Exception:
            pass
        await inter.response.defer()

    def _to_script(self) -> str:
        parts = ["{embed}"]
        if self.data.get("title"):
            parts.append(f"$v{{title: {self.data['title']}}}")
        if self.data.get("description"):
            parts.append(f"$v{{description: {self.data['description']}}}")
        if self.data.get("color"):
            parts.append(f"$v{{color: #{self.data['color'].lstrip('#')}}}")
        if self.data.get("image"):
            parts.append(f"$v{{image: {self.data['image']}}}")
        if self.data.get("thumbnail"):
            parts.append(f"$v{{thumbnail: {self.data['thumbnail']}}}")
        return "\n".join(parts)

    @discord.ui.button(label="Approve & Copy Script", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, inter: discord.Interaction, button: discord.ui.Button):
        script = self._to_script()
        await inter.response.send_message(f"```yaml\n{script}\n```", ephemeral=True)
        
        try:
            await inter.channel.send(f"**Embed script:**\n```yaml\n{script}\n```")
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.edit_message(content="Embed builder cancelled.", view=None)
        self.stop()

async def setup(bot: Vain):
    cog = Socials(bot)
    
    eb = hybrid(
        name="embedbuilder",
        description="Interactive Components v2 embed builder. Dropdowns open modals. Approve to get the script.",
        example=",embedbuilder",
    )(lambda ctx: None)  
    async def _run_eb(ctx: Context):
        view = EmbedBuilderView(ctx.author.id)
        m = await ctx.send("**Embed Builder** (v2)\nSelect fields from the menu, fill modals, then Approve.", view=view)
        view.message = m
    eb.callback = _run_eb
    bot.add_command(eb)
    await bot.add_cog(cog)
