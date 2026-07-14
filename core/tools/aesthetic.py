from __future__ import annotations

import asyncio
import io

import discord
from PIL import Image
import aiohttp


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


async def get_dominant_color(url: str, fallback: int = 0x2b2d31) -> int:
    """Fetch image and return a nice dominant color (not too dark/light)."""
    if not url:
        return fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img = img.resize((100, 100))  
        pixels = list(img.getdata())
        
        color_count = {}
        for p in pixels:
            color_count[p] = color_count.get(p, 0) + 1
        dominant = max(color_count, key=color_count.get)
        r, g, b = dominant
        
        if (r + g + b) < 80:
            r, g, b = min(r + 60, 255), min(g + 60, 255), min(b + 60, 255)
        return (r << 16) + (g << 8) + b
    except Exception:
        return fallback

async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0x5865f2  


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