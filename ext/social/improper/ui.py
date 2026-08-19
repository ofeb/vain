"""Components V2 social UI - repost cards, profile cards, accent colours."""

from __future__ import annotations

import asyncio
import io
import re
from typing import Any, Iterable

import aiohttp
import discord
from discord import ui
from colorthief import ColorThief


def _linkify_caption(caption: str, platform: str) -> str:
    """Turn #hashtags / @mentions into markdown links."""
    text = (caption or "").replace("```", "`\u200b`\u200b`").strip()
    if not text:
        return ""
    if platform == "tiktok":
        base = "https://www.tiktok.com/tag/"
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
    """Compact for repost meta (12.4k)."""
    try:
        value = int(n or 0)
    except Exception:
        return "0"
    if value < 1000:
        return f"{value:,}"
    if value < 1_000_000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}k"
    if value < 1_000_000_000:
        text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}m"
    text = f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".")
    return f"{text}b"


def _full_count(n: int | float | None) -> str:
    """Full comma-separated count for profile cards (678,403,773)."""
    try:
        return f"{int(n or 0):,}"
    except Exception:
        return "0"


_PLATFORM_ACCENTS = {
    "tiktok": 0xFE2C55,
    "instagram": 0xE1306C,
    "twitter": 0x1D9BF0,
    "x": 0x1D9BF0,
    "youtube": 0xFF0000,
    "telegram": 0x2AABEE,
    "twitch": 0x9146FF,
    "snapchat": 0xFFFC00,
    "pinterest": 0xE60023,
}


_PLATFORM_VERIFIED = {
    "instagram": "<:ig_verified:1525867315265142945>",
}


def _platform_key(platform: str) -> str:
    p = (platform or "").lower().strip()
    if p == "x":
        return "twitter"
    return p


def _platform_label(platform: str) -> str:
    return {
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "twitter": "X",
        "youtube": "YouTube",
        "telegram": "Telegram",
        "twitch": "Twitch",
        "snapchat": "Snapchat",
        "pinterest": "Pinterest",
        "brave": "Brave",
        "google": "Google",
    }.get(_platform_key(platform), (platform or "Social").title())


def _profile_url(platform: str, username: str) -> str:
    user = (username or "").lstrip("@")
    plat = _platform_key(platform)
    if not user:
        return ""
    if plat == "tiktok":
        return f"https://www.tiktok.com/@{user}"
    if plat == "instagram":
        return f"https://www.instagram.com/{user}/"
    if plat == "twitter":
        return f"https://x.com/{user}"
    if plat == "youtube":
        handle = user if user.startswith("@") else f"@{user}"
        return f"https://www.youtube.com/{handle}"
    if plat == "telegram":
        return f"https://t.me/{user}"
    if plat == "twitch":
        return f"https://www.twitch.tv/{user}"
    if plat == "snapchat":
        return f"https://www.snapchat.com/add/{user}"
    if plat == "pinterest":
        return f"https://www.pinterest.com/{user}/"
    return ""


def _view_label(platform: str) -> str:
    return {
        "tiktok": "View on TikTok",
        "instagram": "View on Instagram",
        "twitter": "View on X",
        "youtube": "View on YouTube",
        "telegram": "View on Telegram",
        "twitch": "View on Twitch",
        "snapchat": "View on Snapchat",
        "pinterest": "View on Pinterest",
    }.get(_platform_key(platform), "View original")


def _format_stat_line(
    *,
    platform: str,
    like_count: int = 0,
    comment_count: int = 0,
    save_count: int = 0,
    share_count: int = 0,
    play_count: int = 0,
) -> str:
    """Human stats line for repost cards."""
    likes = _compact_count(like_count)
    comments = _compact_count(comment_count)
    plat = _platform_key(platform)
    if plat == "tiktok":
        bits = [f"{likes} likes", f"{comments} comments"]
        if play_count:
            bits.append(f"{_compact_count(play_count)} plays")
        elif share_count:
            bits.append(f"{_compact_count(share_count)} shares")
        return " · ".join(bits)
    if plat == "twitter":
        bits = [f"{likes} likes", f"{comments} replies"]
        if share_count:
            bits.append(f"{_compact_count(share_count)} reposts")
        if play_count:
            bits.append(f"{_compact_count(play_count)} views")
        return " · ".join(bits)
    if plat == "youtube":
        bits = []
        if play_count:
            bits.append(f"{_compact_count(play_count)} views")
        bits.append(f"{likes} likes")
        if comment_count:
            bits.append(f"{comments} comments")
        return " · ".join(bits) if bits else "YouTube"
    if plat == "twitch":
        bits = []
        if play_count:
            bits.append(f"{_compact_count(play_count)} views")
        return " · ".join(bits) if bits else "Twitch"
    if plat == "pinterest":
        bits = []
        if like_count:
            bits.append(f"{likes} reactions")
        if comment_count:
            bits.append(f"{comments} comments")
        return " · ".join(bits) if bits else "Pinterest"
    bits = [f"{likes} likes", f"{comments} comments"]
    if save_count:
        bits.append(f"{_compact_count(save_count)} saves")
    return " · ".join(bits)


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
    play_count: int = 0,
    region: str | None = None,
    music_title: str | None = None,
    music_author: str | None = None,
    music_url: str | None = None,
    attachment: discord.File | None = None,
    attachment_filename: str | None = None,
    page_index: int = 0,
    page_total: int = 1,
    include_actions: bool = False,
) -> list[ui.Container]:
    """Vain Components V2 social card.

    Layout (unique vs guilt samples):
      1. Caption / title (linkified)
      2. MediaGallery
      3. Visible divider
      4. Soft quote meta: [@user] + stats
      5. Optional music / region whisper
      6. Actions attached by SocialRepostView (View / Delete)
    """
    from config import emojis

    plat = _platform_key(platform)
    
    _ = accent
    _ = _PLATFORM_ACCENTS.get(plat)
    c = ui.Container()
    _ = avatar_url

    raw_user = (username or "").lstrip("@").strip()
    display = (display_name or "").strip()
    user = raw_user or (display.lstrip("@") if display else "") or "unknown"
    profile = _profile_url(plat, user if user != "unknown" else "")

    linked = _linkify_caption(
        caption, plat if plat in {"tiktok", "instagram", "twitter"} else "instagram"
    )
    if linked:
        c.add_item(ui.TextDisplay(linked[:1900]))
    else:
        c.add_item(ui.TextDisplay(f"**{display or user}** · {_platform_label(plat)}"))

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
        try:
            c.add_item(ui.MediaGallery(media_item))
        except Exception:
            if current:
                c.add_item(ui.TextDisplay(f"[media]({current})"))
    elif current:
        c.add_item(ui.TextDisplay(f"[media]({current})"))

    try:
        c.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
    except Exception:
        try:
            c.add_item(ui.Separator(visible=True))
        except Exception:
            pass

    stats = _format_stat_line(
        platform=plat,
        like_count=like_count,
        comment_count=comment_count,
        save_count=save_count,
        share_count=share_count,
        play_count=play_count,
    )
    if profile and user != "unknown":
        handle_md = f"[@{user}](<{profile}>)"
    elif user != "unknown":
        handle_md = f"@{user}"
    elif display:
        handle_md = f"**{display}**"
    else:
        handle_md = _platform_label(plat)
    meta_lines = [
        f"{handle_md}",
        f"{stats}",
    ]
    if page_total > 1:
        meta_lines.append(f"slide **{page_index + 1}**/**{page_total}**")
    c.add_item(ui.TextDisplay("\n".join(meta_lines)))

    whisper: list[str] = []
    if music_title:
        music_label = music_title
        if music_author:
            music_label = f"{music_title} - {music_author}"
        if music_url:
            whisper.append(f"{emojis.music} [{music_label}]({music_url})")
        else:
            whisper.append(f"{emojis.music} {music_label}")
    if region:
        whisper.append(f"{emojis.region} {region}")
    if whisper:
        try:
            c.add_item(ui.Separator(visible=False))
        except Exception:
            pass
        c.add_item(ui.TextDisplay("> -# " + "  ·  ".join(whisper)))

    if include_actions:
        link = source_url or profile
        watch = _view_label(plat)
        try:
            c.add_item(ui.Separator(visible=False))
        except Exception:
            pass
        try:
            c.add_item(
                ui.ActionRow(
                    ui.Button(style=discord.ButtonStyle.link, label=watch, url=str(link))
                )
            )
        except Exception:
            pass
    return [c]



def build_profile_container(
    *,
    platform: str,
    username: str,
    display_name: str | None = None,
    bio: str = "",
    avatar_url: str | None = None,
    profile_url: str | None = None,
    followers: int = 0,
    following: int = 0,
    likes: int | None = None,
    posts: int | None = None,
    extra_stats: list[tuple[str, int | str]] | None = None,
    is_private: bool = False,
    is_verified: bool = False,
    accent: int | None = None,
    verified_emoji: str | None = None,
) -> list[ui.Container]:
    """Profile card matching guilt C2 layout.

    ## [Full Name (@username)](url) verified/lock
    divider
    -# **Followers:** `n` · **Following:** `n` · **Posts:** `n`
    """
    plat = _platform_key(platform)
    if accent is None:
        accent = _PLATFORM_ACCENTS.get(plat, 0xE1D2DE)
    raw_user = (username or "").lstrip("@").strip()
    user = raw_user or "unknown"
    name = (display_name or "").strip()
    if not name or name.lstrip("@").lower() == user.lower():
        
        label = f"@{user}" if user != "unknown" else "unknown"
    else:
        label = f"{name} (@{user})" if user != "unknown" else name
    url = profile_url or _profile_url(plat, user if user != "unknown" else "")

    badges: list[str] = []
    if is_verified:
        ve = (verified_emoji or "").strip() or _PLATFORM_VERIFIED.get(plat) or "✓"
        badges.append(ve)
    if is_private:
        badges.append("🔒")
    badge_s = (" " + " ".join(badges)) if badges else ""

    if url and user != "unknown":
        title = f"## [{label}]({url}){badge_s}"
    else:
        title = f"## {label}{badge_s}"

    body_bits = [title]
    bio_clean = (bio or "").strip()
    if bio_clean:
        body_bits.append(bio_clean[:500])

    c = ui.Container()
    
    _ = accent
    header = "\n".join(body_bits)
    if avatar_url:
        try:
            c.add_item(
                ui.Section(
                    ui.TextDisplay(header[:1900]),
                    accessory=ui.Thumbnail(str(avatar_url)),
                )
            )
        except Exception:
            c.add_item(ui.TextDisplay(header[:1900]))
    else:
        c.add_item(ui.TextDisplay(header[:1900]))

    try:
        c.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
    except Exception:
        try:
            c.add_item(ui.Separator(visible=True))
        except Exception:
            pass

    stats: list[str] = [
        f"**Followers:** `{_full_count(followers)}`",
        f"**Following:** `{_full_count(following)}`",
    ]
    if likes is not None:
        stats.append(f"**Likes:** `{_full_count(likes)}`")
    if posts is not None:
        stats.append(f"**Posts:** `{_full_count(posts)}`")
    for label_s, value in extra_stats or []:
        if isinstance(value, (int, float)):
            stats.append(f"**{label_s}:** `{_full_count(value)}`")
        else:
            stats.append(f"**{label_s}:** `{value}`")
    c.add_item(ui.TextDisplay("> -# " + "  ·  ".join(stats)))
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
    """Paginated multi-image social repost with View + Delete actions.

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
        play_count: int = 0,
        region: str | None = None,
        music_title: str | None = None,
        music_author: str | None = None,
        music_url: str | None = None,
        attachment_filename: str | None = None,
        owner_id: int | None = None,
        timeout: float | None = 300,
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
        self.play_count = play_count
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
            "play_count": self.play_count,
            "region": self.region,
            "music_title": self.music_title,
            "music_author": self.music_author,
            "music_url": self.music_url,
            "attachment_filename": self.attachment_filename,
            "page_index": self.index,
            "page_total": max(len(self.media_urls), 1),
        }

    def _can_delete(self, interaction: discord.Interaction) -> bool:
        if self.owner_id and interaction.user and interaction.user.id == self.owner_id:
            return True
        try:
            channel = interaction.channel
            if channel is not None and interaction.user is not None:
                perms = channel.permissions_for(interaction.user)  # type: ignore[arg-type]
                if perms.manage_messages:
                    return True
        except Exception:
            pass
        if interaction.user and getattr(interaction.user, "guild_permissions", None):
            perms = interaction.user.guild_permissions  # type: ignore[union-attr]
            if perms and (perms.manage_messages or perms.administrator):
                return True
        return False

    def _rebuild(self) -> None:
        from config import emojis as _e

        self.clear_items()
        containers = build_social_repost_container(**self._kwargs())
        container = containers[0]

        plat = _platform_key(self.platform)
        raw_user = (self.username or "").lstrip("@").strip()
        display = (self.display_name or "").strip()
        user = raw_user or (display.lstrip("@") if display else "") or "unknown"
        profile = _profile_url(plat, user if user != "unknown" else "")
        watch_label = _view_label(plat)
        link = self.source_url or profile
        if link and not str(link).startswith("http"):
            link = profile or self.source_url

        if len(self.media_urls) > 1:
            try:
                container.add_item(ui.Separator(visible=True))
            except Exception:
                pass
            nav_row = ui.ActionRow()
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
            nav_row.add_item(prev)
            nav_row.add_item(nav)
            nav_row.add_item(nxt)
            container.add_item(nav_row)

        try:
            container.add_item(ui.Separator(visible=False))
        except Exception:
            pass
        action = ui.ActionRow()
        try:
            action.add_item(
                ui.Button(style=discord.ButtonStyle.link, label=watch_label, url=str(link))
            )
        except Exception:
            pass

        delete_emoji = None
        try:
            raw_del = getattr(getattr(_e, "ticket", None), "close", None) or getattr(
                _e, "deny", None
            )
            if raw_del:
                delete_emoji = discord.PartialEmoji.from_str(str(raw_del))
        except Exception:
            delete_emoji = None

        delete_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Delete",
            emoji=delete_emoji,
        )

        async def _delete(interaction: discord.Interaction) -> None:
            if not self._can_delete(interaction):
                await interaction.response.send_message(
                    "only the author or mods can delete this.",
                    ephemeral=True,
                )
                return
            try:
                await interaction.response.defer()
            except Exception:
                pass
            target = interaction.message or self.message
            if target is not None:
                try:
                    await target.delete()
                except discord.HTTPException:
                    try:
                        await interaction.followup.send(
                            "couldn't delete that message.", ephemeral=True
                        )
                    except Exception:
                        pass
            self.stop()

        delete_btn.callback = _delete  # type: ignore[method-assign]
        action.add_item(delete_btn)
        container.add_item(action)

        self.add_item(container)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            bare = layout_from_items(
                build_social_repost_container(**self._kwargs(), include_actions=True),
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
    fallback: int = 0xE1D2DE,
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
    return 0xE1D2DE

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
    if plat == "x":
        plat = "twitter"
    referer = {
        "tiktok": "https://www.tiktok.com/",
        "instagram": "https://www.instagram.com/",
        "twitter": "https://x.com/",
        "youtube": "https://www.youtube.com/",
        "telegram": "https://t.me/",
        "twitch": "https://www.twitch.tv/",
        "snapchat": "https://www.snapchat.com/",
        "pinterest": "https://www.pinterest.com/",
    }.get(plat)

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
