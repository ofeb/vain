from __future__ import annotations

import asyncio

import aiohttp
import discord
from colorthief import ColorThief
from io import BytesIO


def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)


def caption(text: str) -> str:
    return f"-# {text}"


def emphasis(text: str) -> str:
    return f"> -# **{text}**"


def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


def panel_embed(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description or None, url=url)
    if title:
        embed.title = title
    if author:
        if author_icon:
            embed.set_author(name=author, icon_url=author_icon)
        else:
            embed.set_author(name=author)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed


def aesthetic_embed(
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


def reply_embed(
    *,
    color: int,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return aesthetic_embed(color=color, message=message, footer=subtitle, timestamp=False)


async def get_dominant_color(url: str, fallback: int = 0x2A2B2F) -> int:
    """Fetch image and return dominant color using colorthief."""
    if not url:
        return fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()

        def _extract():
            ct = ColorThief(BytesIO(data))
            r, g, b = ct.get_color(quality=1)
            # brighten very dark colors a bit (kept from previous logic)
            if (r + g + b) < 80:
                r = min(r + 60, 255)
                g = min(g + 60, 255)
                b = min(b + 60, 255)
            return (r << 16) + (g << 8) + b

        return await asyncio.to_thread(_extract)
    except Exception:
        return fallback

async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0x2A2B2F


def build_repost_container(
    *,
    platform: str,
    username: str,
    caption: str,
    media_urls: list[str] | None = None,
    stats: str = "",
    source_url: str = "",
    avatar_url: str | None = None,
    accent: int | None = None,
) -> list:
    """Build a clean aesthetic Components v2 container for reposts (IG / TT)."""
    c = discord.ui.Container(accent_colour=accent or 0xE1306C)  
    
    header = f"**{username}**"
    if source_url:
        header = f"[{username}]({source_url})"
    c.add_item(discord.ui.TextDisplay(header))
    if caption:
        
        safe = caption.replace("```", "`\u200b`\u200b`")[:1800]
        c.add_item(discord.ui.TextDisplay(f"> {safe}"))
    c.add_item(discord.ui.Separator())
    
    if media_urls:
        items = []
        for u in media_urls[:4]:  
            items.append({"media": {"url": u}})
        if items:
            c.add_item(discord.ui.MediaGallery(items=items))
    if stats:
        c.add_item(discord.ui.TextDisplay(f"-# {stats}"))
    footer = f"-# {platform}"
    if source_url:
        footer += f" • [view]({source_url})"
    c.add_item(discord.ui.TextDisplay(footer))
    return [c]