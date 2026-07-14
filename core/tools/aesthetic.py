from __future__ import annotations

import discord


def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)


def caption(text: str) -> str:
    return f"-# {text}"


def emphasis(text: str) -> str:
    return f"> -# **{text}**"


def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def label_line(label: str, value: str) -> str:
    return f"**{label}** » {value}"


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