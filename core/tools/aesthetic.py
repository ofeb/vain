from __future__ import annotations

import asyncio
import re
from io import BytesIO
from typing import Any, Iterable, Sequence

import aiohttp
import discord
from colorthief import ColorThief
from discord import ui


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


async def get_dominant_color(url: str, fallback: int = 0x5865F2) -> int:
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
    return 0x5865F2


def _accent_from_embed(embed: discord.Embed) -> int | None:
    colour = embed.colour or embed.color
    if colour is None:
        return None
    try:
        return int(colour.value)
    except Exception:
        return None


def _blankish(value: str | None) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text in {"\u200b", "‎", "​"}


def view_has_interactive_controls(view: ui.View | ui.LayoutView | None) -> bool:
    """True when a classic View has buttons/selects that need the View dispatch path."""
    if view is None or isinstance(view, ui.LayoutView):
        return False
    for child in getattr(view, "children", ()) or ():
        if isinstance(child, ui.Select):
            return True
        if isinstance(child, ui.Button) and getattr(child, "url", None) is None:
            return True
    return False


def _link_buttons_from_view(view: ui.View | None) -> list[ui.Button]:
    if view is None or isinstance(view, ui.LayoutView):
        return []
    out: list[ui.Button] = []
    for child in getattr(view, "children", ()) or ():
        if isinstance(child, ui.Button) and getattr(child, "url", None):
            out.append(
                ui.Button(
                    style=child.style or discord.ButtonStyle.link,
                    label=child.label,
                    url=child.url,
                    emoji=child.emoji,
                    disabled=child.disabled,
                )
            )
    return out


def embed_to_container(
    embed: discord.Embed,
    *,
    extra_rows: Sequence[ui.ActionRow] | None = None,
    attachment_files: Sequence[discord.File] | None = None,
) -> ui.Container:
    """Convert a rich embed into a Components V2 container with dividers."""
    accent = _accent_from_embed(embed)
    container = ui.Container(accent_colour=accent)

    
    author_name = embed.author.name if embed.author else None
    author_icon = embed.author.icon_url if embed.author else None
    thumb = embed.thumbnail.url if embed.thumbnail else None
    title = embed.title
    if title and embed.url:
        title_md = f"### [{title}]({embed.url})"
    elif title:
        title_md = f"### {title}"
    else:
        title_md = None

    header_bits: list[str] = []
    if author_name and not _blankish(author_name):
        header_bits.append(f"**{author_name}**")
    if title_md:
        header_bits.append(title_md)

    media_url = thumb or author_icon
    if header_bits and media_url:
        try:
            container.add_item(
                ui.Section(
                    ui.TextDisplay("\n".join(header_bits)),
                    accessory=ui.Thumbnail(media=str(media_url)),
                )
            )
        except Exception:
            container.add_item(ui.TextDisplay("\n".join(header_bits)))
    elif header_bits:
        container.add_item(ui.TextDisplay("\n".join(header_bits)))

    if header_bits and (embed.description or embed.fields or embed.image or embed.footer):
        container.add_item(ui.Separator(visible=True))

    if embed.description and not _blankish(embed.description):
        container.add_item(ui.TextDisplay(str(embed.description)))

    if embed.fields:
        if embed.description and not _blankish(embed.description):
            container.add_item(ui.Separator(visible=True))
        field_chunks: list[str] = []
        for field in embed.fields:
            name = "" if _blankish(field.name) else str(field.name)
            value = "" if _blankish(field.value) else str(field.value)
            if name and value:
                field_chunks.append(f"**{name}**\n{value}")
            elif value:
                field_chunks.append(value)
            elif name:
                field_chunks.append(f"**{name}**")
        if field_chunks:
            container.add_item(ui.TextDisplay("\n\n".join(field_chunks)))

    
    image_url = embed.image.url if embed.image else None
    if image_url:
        container.add_item(ui.Separator(visible=True))
        try:
            if str(image_url).startswith("attachment://") and attachment_files:
                fname = str(image_url).split("attachment://", 1)[-1]
                match = next((f for f in attachment_files if f.filename == fname), None)
                if match is not None:
                    container.add_item(ui.MediaGallery(discord.MediaGalleryItem(match)))
                else:
                    container.add_item(ui.MediaGallery(discord.MediaGalleryItem(str(image_url))))
            else:
                container.add_item(ui.MediaGallery(discord.MediaGalleryItem(str(image_url))))
        except Exception:
            container.add_item(ui.TextDisplay(f"[image]({image_url})"))

    
    if attachment_files and not image_url:
        for f in attachment_files[:1]:
            try:
                container.add_item(ui.File(f))
            except Exception:
                pass

    if embed.footer and not _blankish(embed.footer.text):
        container.add_item(ui.Separator(visible=True))
        footer = str(embed.footer.text)
        if embed.timestamp:
            try:
                footer = f"{footer} · <t:{int(embed.timestamp.timestamp())}:R>"
            except Exception:
                pass
        container.add_item(ui.TextDisplay(f"-# {footer}"))
    elif embed.timestamp and not (embed.footer and embed.footer.text):
        try:
            container.add_item(ui.Separator(visible=True))
            container.add_item(
                ui.TextDisplay(f"-# <t:{int(embed.timestamp.timestamp())}:R>")
            )
        except Exception:
            pass

    if extra_rows:
        container.add_item(ui.Separator(visible=True))
        for row in extra_rows:
            container.add_item(row)

    return container


def layout_from_items(
    items: Iterable[ui.Item],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    layout = ui.LayoutView(timeout=timeout)
    for item in items:
        layout.add_item(item)
    return layout


def layout_from_components(
    components: Sequence[Any] | Any,
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    """Wrap Container / Item list into a LayoutView (for components= send kwarg)."""
    if isinstance(components, ui.LayoutView):
        return components
    if not isinstance(components, (list, tuple)):
        components = [components]
    return layout_from_items(components, timeout=timeout)


def embed_to_layout(
    embed: discord.Embed,
    *,
    view: ui.View | None = None,
    attachment_files: Sequence[discord.File] | None = None,
    timeout: float | None = 180,
) -> ui.LayoutView:
    link_buttons = _link_buttons_from_view(view)
    extra_rows: list[ui.ActionRow] = []
    if link_buttons:
        
        for i in range(0, len(link_buttons), 5):
            row = ui.ActionRow(*link_buttons[i : i + 5])
            extra_rows.append(row)
    container = embed_to_container(
        embed,
        extra_rows=extra_rows or None,
        attachment_files=attachment_files,
    )
    return layout_from_items([container], timeout=timeout)


def embeds_to_layout(
    embeds: Sequence[discord.Embed],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    containers = [embed_to_container(e) for e in embeds]
    return layout_from_items(containers, timeout=timeout)


def panel_container(
    *,
    accent: int | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    thumbnail: str | None = None,
    buttons: Sequence[ui.Button] | None = None,
) -> ui.Container:
    """Build a clean panel container with separators (preferred over panel_embed)."""
    c = ui.Container(accent_colour=accent)

    header = f"**{title}**" if title else None
    if header and thumbnail:
        try:
            body_text = header if not subtitle else f"{header}\n-# {subtitle}"
            c.add_item(
                ui.Section(
                    ui.TextDisplay(body_text),
                    accessory=ui.Thumbnail(media=str(thumbnail)),
                )
            )
        except Exception:
            c.add_item(ui.TextDisplay(header))
            if subtitle:
                c.add_item(ui.TextDisplay(f"-# {subtitle}"))
    elif header:
        c.add_item(ui.TextDisplay(header))
        if subtitle:
            c.add_item(ui.TextDisplay(f"-# {subtitle}"))
    elif subtitle:
        c.add_item(ui.TextDisplay(f"-# {subtitle}"))

    if lines:
        if header or subtitle:
            c.add_item(ui.Separator(visible=True))
        c.add_item(ui.TextDisplay(body(*lines)))

    if footer:
        c.add_item(ui.Separator(visible=True))
        c.add_item(ui.TextDisplay(caption(footer)))

    if buttons:
        c.add_item(ui.Separator(visible=True))
        for i in range(0, len(list(buttons)), 5):
            chunk = list(buttons)[i : i + 5]
            c.add_item(ui.ActionRow(*chunk))

    return c


def panel_layout(**kwargs: Any) -> ui.LayoutView:
    return layout_from_items([panel_container(**kwargs)])


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



_TIKTOK_FOOTER_ICON = "https://cdn-icons-png.flaticon.com/512/3046/3046121.png"
_INSTAGRAM_FOOTER_ICON = "https://cdn-icons-png.flaticon.com/512/2111/2111463.png"


def build_social_repost_embed(
    *,
    platform: str,
    username: str,
    display_name: str | None = None,
    caption: str = "",
    avatar_url: str | None = None,
    source_url: str = "",
    color: int | None = None,
    like_count: int = 0,
    comment_count: int = 0,
    save_count: int = 0,
    share_count: int = 0,
    region: str | None = None,
    music_title: str | None = None,
    music_author: str | None = None,
    image_url: str | None = None,
) -> discord.Embed:
    """Minimal classic embed for TikTok / Instagram reposts (no containers)."""
    from core.managers.values import emojis

    name = display_name or username or "unknown"
    user = (username or "unknown").lstrip("@")
    if platform == "tiktok":
        profile = f"https://www.tiktok.com/@{user}"
        footer_icon = _TIKTOK_FOOTER_ICON
        footer_name = "TikTok"
    else:
        profile = f"https://www.instagram.com/{user}/"
        footer_icon = _INSTAGRAM_FOOTER_ICON
        footer_name = "Instagram"

    desc_parts: list[str] = []
    linked = _linkify_caption(caption, platform)
    if linked:
        desc_parts.append(linked)
    if music_title:
        music_label = music_title
        if music_author:
            music_label = f"{music_title} — {music_author}"
        desc_parts.append(f"-# {emojis.music} {music_label}")

    embed = discord.Embed(
        description="\n\n".join(desc_parts) if desc_parts else None,
        color=color or 0x2A2B2F,
        url=source_url or profile,
    )
    
    author_name = f"{name} (@{user})"
    if avatar_url:
        embed.set_author(name=author_name, icon_url=str(avatar_url), url=profile)
    else:
        embed.set_author(name=author_name, url=profile)

    if image_url:
        embed.set_image(url=str(image_url))

    
    stats = [
        f"{emojis.likes} {_compact_count(like_count)}",
        f"{emojis.comments} {_compact_count(comment_count)}",
        f"{emojis.saves} {_compact_count(save_count)}",
    ]
    if share_count:
        stats.append(f"{emojis.reposts} {_compact_count(share_count)}")
    if region:
        stats.append(f"{emojis.region} {region}")
    footer_text = " • ".join(stats)
    if footer_name:
        footer_text = f"{footer_text}  ·  {footer_name}" if footer_text else footer_name
    embed.set_footer(text=footer_text[:2048], icon_url=footer_icon)
    return embed


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
) -> list[ui.Container]:
    """Heist-style V2 repost container (section + gallery + stats + watch button).

    Accent should be the bot dominant colour.
    """
    from core.managers.values import emojis

    c = ui.Container(accent_colour=accent or 0x5865F2)
    name = display_name or username or "unknown"
    user = (username or "unknown").lstrip("@")
    if platform == "tiktok":
        profile = f"https://www.tiktok.com/@{user}"
        watch_label = "Watch on TikTok"
        watch_emoji = None
    else:
        profile = f"https://www.instagram.com/{user}/"
        watch_label = "View on Instagram"
        watch_emoji = None

    body_lines = [
        f"{emojis.human} Posted by **{name}** [(@{user})]({profile})",
    ]
    linked = _linkify_caption(caption, platform)
    if linked:
        body_lines.append("")
        body_lines.append(f"> {linked}")
    if music_title:
        music_label = music_title
        if music_author:
            music_label = f"{music_title} — {music_author}"
        if music_url:
            body_lines.append(f"-# {emojis.music} [{music_label}]({music_url})")
        else:
            body_lines.append(f"-# {emojis.music} {music_label}")

    header = "\n".join(body_lines)
    if avatar_url:
        try:
            c.add_item(
                ui.Section(
                    ui.TextDisplay(header),
                    accessory=ui.Thumbnail(media=str(avatar_url)),
                )
            )
        except Exception:
            c.add_item(ui.TextDisplay(header))
    else:
        c.add_item(ui.TextDisplay(header))

    
    gallery_items: list[discord.MediaGalleryItem] = []
    for u in (media_urls or [])[:4]:
        if not u:
            continue
        try:
            gallery_items.append(discord.MediaGalleryItem(str(u)))
        except Exception:
            continue
    if gallery_items:
        try:
            c.add_item(ui.MediaGallery(*gallery_items))
        except Exception:
            pass
    elif attachment is not None:
        try:
            c.add_item(ui.File(attachment))
        except Exception:
            pass

    c.add_item(ui.Separator(visible=True))

    stats_bits = [
        f"{emojis.likes} {_compact_count(like_count)}",
        f"{emojis.comments} {_compact_count(comment_count)}",
        f"{emojis.saves} {_compact_count(save_count)}",
    ]
    if share_count:
        stats_bits.append(f"{emojis.repost} {_compact_count(share_count)}")
    if region:
        stats_bits.append(f"{emojis.region} {region}")
    c.add_item(ui.TextDisplay("-# " + " • ".join(stats_bits)))

    
    row = ui.ActionRow()
    if source_url:
        btn_kw: dict[str, Any] = {
            "style": discord.ButtonStyle.link,
            "label": watch_label,
            "url": source_url,
        }
        if watch_emoji:
            btn_kw["emoji"] = watch_emoji
        row.add_item(ui.Button(**btn_kw))
    else:
        row.add_item(
            ui.Button(
                style=discord.ButtonStyle.link,
                label=watch_label,
                url=profile,
            )
        )
    c.add_item(row)
    return [c]


def build_repost_container(
    *,
    platform: str,
    username: str,
    caption: str = "",
    media_urls: list[str] | None = None,
    stats: str = "",
    source_url: str = "",
    avatar_url: str | None = None,
    accent: int | None = None,
    attachment: discord.File | None = None,
    **kwargs: Any,
) -> list[ui.Container]:
    """Backward-compatible wrapper → heist-style social repost container."""
    return build_social_repost_container(
        platform=platform,
        username=username,
        caption=caption,
        media_urls=media_urls,
        source_url=source_url,
        avatar_url=avatar_url,
        accent=accent,
        attachment=attachment,
        **{k: v for k, v in kwargs.items() if k in {
            "display_name", "like_count", "comment_count", "save_count",
            "share_count", "region", "music_title", "music_author", "music_url",
        }},
    )


def build_repost_layout(**kwargs: Any) -> ui.LayoutView:
    return layout_from_components(build_social_repost_container(**kwargs))
