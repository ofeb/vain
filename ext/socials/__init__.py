from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import textwrap
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, TYPE_CHECKING

import aiohttp
import discord
from discord import ui
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.discord.package import Package

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from core.managers.values import color
from colorthief import ColorThief


_TIKTOK_FOOTER_ICON = "https://cdn-icons-png.flaticon.com/512/3046/3046121.png"
_INSTAGRAM_FOOTER_ICON = "https://cdn-icons-png.flaticon.com/512/2111/2111463.png"
def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def c2(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def _linkify_caption(caption: str, platform: str) -> str:
    """Turn #hashtags into markdown links (heist-style)."""
    text = (caption or "").replace("```", "`\u200b`\u200b`").strip()
    if not text:
        return ""
    if platform == "tiktok":
        base = "https://tiktok.com/tag/"
    else:
        base = "https://www.instagram.com/explore/tags/"

    def _hash(m: re.Match[str]) -> str:
        tag = m.group(1)
        return f"[#{tag}](<{base}{tag}>)"

    def _mention(m: re.Match[str]) -> str:
        user = m.group(1)
        if platform == "tiktok":
            return f"[@{user}](<https://www.tiktok.com/@{user}>)"
        return f"[@{user}](<https://www.instagram.com/{user}/>)"

    text = re.sub(r"#(\w+)", _hash, text)
    text = re.sub(r"@(\w+)", _mention, text)
    return text[:1900]

def _compact_count(n: int | float | None) -> str:
    try:
        value = int(n or 0)
    except Exception:
        return "0"
    if value < 1000:
        return str(value)
    if value < 1_000_000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}k"
    text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
    return f"{text}m"

def build_social_repost_container(
    *,
    platform: str,
    username: str,
    display_name: str | None = None,
    caption: str = "",
    media_urls: list[str] | None = None,
    avatar_url: str | None = None,
    source_url: str = "",
    accent: int | None = None,
    like_count: int = 0,
    comment_count: int = 0,
    save_count: int = 0,
    share_count: int = 0,
    region: str | None = None,
    music_title: str | None = None,
    music_author: str | None = None,
    music_url: str | None = None,
    attachment: discord.File | None = None,
    attachment_filename: str | None = None,
    page_index: int = 0,
    page_total: int = 1,
) -> list[ui.Container]:
    """Components V2 social repost panel.

    Uploaded videos/images use **MediaGallery** (type 12) with
    ``attachment://filename`` so Discord shows an inline player (not File type 13).
    """
    from core.managers.values import emojis

    accent = accent or 0x2A2B2F
    c = ui.Container(accent_colour=int(accent))
    name = display_name or username or "unknown"
    user = (username or "unknown").lstrip("@")
    plat = (platform or "").lower()
    if plat == "tiktok":
        profile = f"https://www.tiktok.com/@{user}"
        platform_label = "TikTok"
        watch_label = "Open on TikTok"
    else:
        profile = f"https://www.instagram.com/{user}/"
        platform_label = "Instagram"
        watch_label = "Open on Instagram"

    title_line = f"**{name}**"
    handle_line = f"-# {emojis.human} [@{user}]({profile}) · **{platform_label}**"
    header_md = f"{title_line}\n{handle_line}"
    if avatar_url:
        try:
            c.add_item(
                ui.Section(
                    ui.TextDisplay(header_md),
                    accessory=ui.Thumbnail(media=str(avatar_url)),
                )
            )
        except Exception:
            c.add_item(ui.TextDisplay(header_md))
    else:
        c.add_item(ui.TextDisplay(header_md))

    linked = _linkify_caption(caption, plat if plat in {"tiktok", "instagram"} else "instagram")
    if linked:
        c.add_item(ui.Separator(visible=True))
        quoted = "\n".join(f"> {line}" if line else ">" for line in linked.splitlines())
        c.add_item(ui.TextDisplay(quoted[:1900]))

    if music_title:
        music_label = music_title
        if music_author:
            music_label = f"{music_title} — {music_author}"
        c.add_item(ui.Separator(visible=False))
        if music_url:
            c.add_item(ui.TextDisplay(f"-# {emojis.music} [{music_label}]({music_url})"))
        else:
            c.add_item(ui.TextDisplay(f"-# {emojis.music} {music_label}"))

    urls = [u for u in (media_urls or []) if u]
    if page_total < 1:
        page_total = 1
    page_index = max(0, min(page_index, max(page_total - 1, 0)))
    current = urls[page_index] if urls and page_index < len(urls) else (urls[0] if urls else None)

    
    
    file_name = attachment_filename or (attachment.filename if attachment is not None else None)
    media_item: discord.MediaGalleryItem | None = None
    if file_name:
        try:
            if attachment is not None:
                media_item = discord.MediaGalleryItem(attachment)
            else:
                media_item = discord.MediaGalleryItem(f"attachment://{file_name}")
        except Exception:
            try:
                media_item = discord.MediaGalleryItem(f"attachment://{file_name}")
            except Exception:
                media_item = None
    elif current:
        try:
            media_item = discord.MediaGalleryItem(str(current))
        except Exception:
            media_item = None

    if media_item is not None:
        c.add_item(ui.Separator(visible=True))
        try:
            c.add_item(ui.MediaGallery(media_item))
        except Exception:
            if current:
                c.add_item(ui.TextDisplay(f"[media]({current})"))
    elif current:
        c.add_item(ui.Separator(visible=True))
        c.add_item(ui.TextDisplay(f"[media]({current})"))

    stats_bits = [
        f"{emojis.likes} **{_compact_count(like_count)}**",
        f"{emojis.comments} **{_compact_count(comment_count)}**",
        f"{emojis.saves} **{_compact_count(save_count)}**",
    ]
    repost_emoji = getattr(emojis, "reposts", None) or emojis.repost
    if share_count:
        stats_bits.append(f"{repost_emoji} **{_compact_count(share_count)}**")
    if region:
        stats_bits.append(f"{emojis.region} {region}")

    c.add_item(ui.Separator(visible=True))
    footer_bits = [" · ".join(stats_bits)]
    if page_total > 1:
        footer_bits.append(f"slide **{page_index + 1}**/**{page_total}**")
    c.add_item(ui.TextDisplay("-# " + "  ·  ".join(footer_bits)))

    link = source_url or profile
    row = ui.ActionRow(
        ui.Button(style=discord.ButtonStyle.link, label=watch_label, url=link)
    )
    c.add_item(ui.Separator(visible=False))
    c.add_item(row)
    return [c]

def layout_from_items(
    items: Iterable[ui.Item],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    layout = ui.LayoutView(timeout=timeout)
    for item in items:
        layout.add_item(item)
    return layout

class SocialRepostView(ui.LayoutView):
    """Paginated multi-image social repost (TikTok photos / IG carousels).

    For videos, pass ``attachment_filename`` matching the ``discord.File``
    uploaded with the message so MediaGallery can play ``attachment://name``.
    """

    def __init__(
        self,
        *,
        platform: str,
        username: str,
        media_urls: list[str],
        display_name: str | None = None,
        caption: str = "",
        avatar_url: str | None = None,
        source_url: str = "",
        accent: int | None = None,
        like_count: int = 0,
        comment_count: int = 0,
        save_count: int = 0,
        share_count: int = 0,
        region: str | None = None,
        music_title: str | None = None,
        music_author: str | None = None,
        music_url: str | None = None,
        attachment_filename: str | None = None,
        owner_id: int | None = None,
        timeout: float | None = 180,
    ) -> None:
        super().__init__(timeout=timeout)
        self.platform = platform
        self.username = username
        self.display_name = display_name
        self.caption = caption
        self.avatar_url = avatar_url
        self.source_url = source_url
        self.accent = accent
        self.like_count = like_count
        self.comment_count = comment_count
        self.save_count = save_count
        self.share_count = share_count
        self.region = region
        self.music_title = music_title
        self.music_author = music_author
        self.music_url = music_url
        self.attachment_filename = attachment_filename
        self.media_urls = [u for u in media_urls if u]
        self.index = 0
        self.owner_id = owner_id
        self.message: discord.Message | None = None
        self._rebuild()

    def _kwargs(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "username": self.username,
            "display_name": self.display_name,
            "caption": self.caption,
            "media_urls": self.media_urls,
            "avatar_url": self.avatar_url,
            "source_url": self.source_url,
            "accent": self.accent,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "save_count": self.save_count,
            "share_count": self.share_count,
            "region": self.region,
            "music_title": self.music_title,
            "music_author": self.music_author,
            "music_url": self.music_url,
            "attachment_filename": self.attachment_filename,
            "page_index": self.index,
            "page_total": max(len(self.media_urls), 1),
        }

    def _rebuild(self) -> None:
        from core.managers.values import emojis as _e

        self.clear_items()
        containers = build_social_repost_container(**self._kwargs())
        container = containers[0]

        if len(self.media_urls) > 1:
            container.add_item(ui.Separator(visible=True))
            row = ui.ActionRow()
            prev = ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(_e.paginator.previous),
                disabled=self.index <= 0,
            )
            nav = ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(_e.paginator.navigate),
                label=f"{self.index + 1}/{len(self.media_urls)}",
                disabled=True,
            )
            nxt = ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(_e.paginator.next),
                disabled=self.index >= len(self.media_urls) - 1,
            )

            async def _prev(interaction: discord.Interaction) -> None:
                if self.owner_id and interaction.user.id != self.owner_id:
                    await interaction.response.send_message("not your repost.", ephemeral=True)
                    return
                self.index = max(0, self.index - 1)
                self._rebuild()
                await interaction.response.edit_message(view=self)

            async def _next(interaction: discord.Interaction) -> None:
                if self.owner_id and interaction.user.id != self.owner_id:
                    await interaction.response.send_message("not your repost.", ephemeral=True)
                    return
                self.index = min(len(self.media_urls) - 1, self.index + 1)
                self._rebuild()
                await interaction.response.edit_message(view=self)

            prev.callback = _prev  # type: ignore[method-assign]
            nxt.callback = _next  # type: ignore[method-assign]
            row.add_item(prev)
            row.add_item(nav)
            row.add_item(nxt)
            container.add_item(row)

        self.add_item(container)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            
            bare = layout_from_items(
                build_social_repost_container(**self._kwargs()),
                timeout=None,
            )
            await self.message.edit(view=bare)
        except Exception:
            pass


def _rgb_to_int(r: int, g: int, b: int) -> int:
    return (int(r) << 16) + (int(g) << 8) + int(b)


def _color_vibrance(rgb: tuple[int, int, int]) -> float:
    """Higher = more saturated / vivid (prefer over muddy greys)."""
    r, g, b = (x / 255.0 for x in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx <= 0:
        return 0.0
    sat = (mx - mn) / mx
    return sat * mx


def _pick_accent_from_palette(
    dominant: tuple[int, int, int],
    palette: list[tuple[int, int, int]] | None = None,
) -> tuple[int, int, int]:
    """Pick the most vivid swatch so accents match creator art, not greys."""
    candidates = [dominant]
    if palette:
        candidates.extend(palette)
    usable = [
        c
        for c in candidates
        if 30 < sum(c) < 720 and _color_vibrance(c) >= 0.08
    ]
    if not usable:
        usable = list(candidates)
    best = max(usable, key=_color_vibrance)
    r, g, b = best
    if r + g + b < 90:
        r, g, b = min(r + 70, 255), min(g + 70, 255), min(b + 70, 255)
    return (r, g, b)


def _colorthief_from_bytes(data: bytes) -> int | None:
    if not data or len(data) < 64:
        return None
    head = data.lstrip()[:20]
    if head.startswith((b"<", b"{", b"[")) or head.upper().startswith(b"<!DOCTYPE"):
        return None
    try:
        ct = ColorThief(io.BytesIO(data))
        dominant = ct.get_color(quality=1)
        try:
            palette = ct.get_palette(color_count=6, quality=1) or []
        except Exception:
            palette = []
        r, g, b = _pick_accent_from_palette(dominant, list(palette))
        return _rgb_to_int(r, g, b)
    except Exception:
        return None


async def get_dominant_color(
    url: str,
    fallback: int = 0x5865F2,
    *,
    referer: str | None = None,
) -> int:
    """Fetch image and return a vivid dominant colour via colorthief."""
    if not url:
        return fallback
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(str(url), allow_redirects=True) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()
        color = await asyncio.to_thread(_colorthief_from_bytes, data)
        return color if color is not None else fallback
    except Exception:
        return fallback


async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0x5865F2


async def get_repost_accent_color(
    bot,
    *,
    avatar_url: str | None = None,
    thumbnail_url: str | None = None,
    platform: str | None = None,
) -> int:
    """Accent from creator avatar (then video thumb); fall back to bot colour."""
    bot_color = await get_bot_dominant_color(bot)
    plat = (platform or "").lower()
    referer = (
        "https://www.tiktok.com/"
        if plat == "tiktok"
        else "https://www.instagram.com/"
        if plat == "instagram"
        else None
    )

    for candidate in (avatar_url, thumbnail_url):
        if not candidate:
            continue
        color = await get_dominant_color(
            str(candidate),
            fallback=0,
            referer=referer,
        )
        if color:
            return color
    return bot_color



from core.networks.media.compress import discord_upload_limit, fit_for_discord
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
        embed = c2(
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
        embed = c2(
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

                    if os.path.getsize(filepath) > 100 * 1024 * 1024:
                        await ctx.fail("File is too large to process.")
                        return

                    with open(filepath, "rb") as f:
                        data = f.read()

                    filename = result.get("filename", "tiktok.mp4")
                    file = await self._prepare_file(ctx, data, filename=filename)
                    if file is None:
                        return
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
        embed = c2(
            color=color.base,
            title="TikTok Video",
            message="\n".join(lines),
        )
        if post.avatar_url:
            embed.set_thumbnail(url=post.avatar_url)
        await ctx.send(embed=embed)

    @hybrid(
        name="repost",
        description="Repost TikTok posts / Instagram reels",
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

    @staticmethod
    def _is_video_url(u: str) -> bool:
        lu = (u or "").lower()
        
        image_hint = any(
            token in lu
            for token in (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".gif",
                "mime_type=image",
                "/image/",
                "avatar",
                "thumbnail",
                "~tplv-",
            )
        )
        video_hint = any(
            token in lu
            for token in (
                ".mp4",
                ".webm",
                ".mov",
                "mime_type=video",
                "/video/",
                "video_mp4",
                "playwm",
                "play?",
                "/play",
                "aweme",
                "/v/t16/",
                "/v/t50/",
                "tikwm.com/video",
                "tikmate",
                "musical.ly",
            )
        )
        if image_hint and not video_hint:
            return False
        return video_hint

    @staticmethod
    def _looks_like_video_bytes(data: bytes | None) -> bool:
        """True when *data* is large enough and not an HTML/JSON error body."""
        if not data or len(data) < 2048:
            return False
        head = data.lstrip()[:64]
        if head.startswith((b"<", b"{", b"[")) or head.upper().startswith(b"<!DOCTYPE"):
            return False
        
        if b"ftyp" in data[:64]:
            return True
        if data[:4] == b"\x1aE\xdf\xa3":
            return True
        if data[:4] == b"RIFF" and data[8:12] != b"WEBP":
            return True
        
        return b"\x00" in data[:16]

    def _upload_limit(self, ctx: Context) -> int:
        return discord_upload_limit(getattr(ctx, "guild", None))

    async def _download_bytes(
        self,
        media_url: str,
        *,
        platform: str = "",
        max_bytes: int | None = None,
    ) -> bytes | None:
        """Download media. Large files are kept so they can be compressed later."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": (
                "https://www.instagram.com/"
                if platform == "instagram"
                else "https://www.tiktok.com/"
            ),
        }
        
        base_limit = max_bytes if max_bytes is not None else 24 * 1024 * 1024
        hard_cap = max(base_limit * 4, 100 * 1024 * 1024)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    media_url, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        return None
                    
                    cl = resp.headers.get("Content-Length")
                    if cl and cl.isdigit() and int(cl) > hard_cap:
                        return None
                    data = await resp.read()
                    if not data or len(data) > hard_cap:
                        return None
                    return data
        except Exception:
            return None

    async def _prepare_file(
        self,
        ctx: Context,
        data: bytes,
        *,
        filename: str,
    ) -> discord.File | None:
        """Compress if needed and build a Discord file under the guild limit."""
        if not data:
            return None
        limit = self._upload_limit(ctx)
        fitted, name = await fit_for_discord(
            data,
            filename=filename,
            guild=getattr(ctx, "guild", None),
            max_bytes=limit,
        )
        if len(fitted) > limit:
            mb = len(fitted) / (1024 * 1024)
            lim_mb = limit / (1024 * 1024)
            await ctx.fail(
                f"Video is still too large after compression "
                f"({mb:.1f}MB / {lim_mb:.0f}MB limit)."
            )
            return None
        return discord.File(io.BytesIO(fitted), filename=name)

    async def _ytdlp_file(
        self,
        ctx: Context,
        source_url: str,
        platform: str,
    ) -> discord.File | None:
        """Download playable media via yt-dlp when CDN URL is unavailable."""
        loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory(prefix="repost-") as tmp:
            result = await loop.run_in_executor(None, _ytdlp_download_sync, source_url, tmp)
            if not result or not result.get("filepath"):
                return None
            filepath = result["filepath"]
            if not os.path.exists(filepath):
                return None
            
            if os.path.getsize(filepath) > 100 * 1024 * 1024:
                return None
            with open(filepath, "rb") as fh:
                data = fh.read()
            ext = os.path.splitext(result.get("filename") or "media.mp4")[1] or ".mp4"
            return await self._prepare_file(ctx, data, filename=f"{platform}{ext}")

    async def _repost(self, ctx: Context, url: str) -> None:
        """Fetch TikTok/Instagram media and send Components V2 repost panel.

        Videos attach as a file under the panel. Multi-image sets (TikTok photos /
        Instagram carousels) paginate like the help menu.
        """

        url = (url or "").strip()
        if not url:
            await ctx.warn("Provide a TikTok or Instagram URL.")
            return

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
        
        wants_video = bool(
            video_urls
            or post.is_video
            or "/reel" in (post.url or url).lower()
            or "/video/" in (post.url or url).lower()
        )
        limit = self._upload_limit(ctx)
        thumb = None
        if isinstance(post.raw, dict):
            thumb = post.raw.get("thumbnail_url") or post.raw.get("cover")
        accent = await get_repost_accent_color(
            self.bot,
            avatar_url=post.avatar_url,
            thumbnail_url=str(thumb) if thumb else None,
            platform=post.platform,
        )

        upload: discord.File | None = None
        display_media = image_urls[:]
        
        post_id = post.raw.get("id") if isinstance(post.raw, dict) else None
        if post_id and str(post_id).isdigit():
            video_filename = f"{post_id}.mp4"
        else:
            video_filename = f"{(post.platform or 'video').lower()}.mp4"

        if wants_video:
            data: bytes | None = None
            
            candidates = list(dict.fromkeys([*video_urls, *media_urls]))
            for media_url in candidates:
                blob = await self._download_bytes(
                    media_url, platform=post.platform, max_bytes=limit
                )
                if self._looks_like_video_bytes(blob):
                    data = blob
                    break
            if data:
                upload = await self._prepare_file(
                    ctx, data, filename=video_filename
                )
                if upload is None:
                    return
            else:
                upload = await self._ytdlp_file(ctx, post.url or url, post.platform)
                if upload is None:
                    await ctx.fail("Could not download that video.")
                    return
            
            display_media = []
            video_filename = upload.filename or video_filename
        elif image_urls:
            display_media = image_urls
        else:
            upload = await self._ytdlp_file(ctx, post.url or url, post.platform)
            if upload is None and not display_media:
                await ctx.fail("Could not get media for that post.")
                return
            if upload is not None:
                video_filename = upload.filename or video_filename
                display_media = []

        view = SocialRepostView(
            platform=post.platform,
            username=post.username,
            display_name=post.display_name or post.username,
            caption=post.caption or "",
            media_urls=display_media,
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
            attachment_filename=(upload.filename if upload is not None else None),
            owner_id=ctx.author.id,
        )

        send_kw: dict = {"view": view}
        if upload is not None:
            
            
            try:
                upload.fp.seek(0)
            except Exception:
                pass
            send_kw["file"] = upload

        try:
            msg = await ctx.send(**send_kw)
            view.message = msg
        except discord.HTTPException as exc:
            if upload is not None and (
                getattr(exc, "code", None) == 40005 or exc.status == 413
            ):
                try:
                    upload.fp.seek(0)
                except Exception:
                    pass
                raw = upload.fp.read()
                tighter = max(8 * 1024 * 1024, limit // 2)
                fitted, name = await fit_for_discord(
                    raw,
                    filename=upload.filename or video_filename,
                    max_bytes=tighter,
                )
                if len(fitted) > tighter:
                    await ctx.fail(
                        "Video is too large for Discord even after compression."
                    )
                    return
                
                view.attachment_filename = name
                view._rebuild()
                msg = await ctx.send(
                    file=discord.File(io.BytesIO(fitted), filename=name),
                    view=view,
                )
                view.message = msg
            else:
                raise

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
    from .builders import register_builders
    cog = Socials(bot)
    await register_builders(bot)
    await bot.add_cog(cog)
