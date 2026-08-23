"""C2 container builder and utility views.

use c2() to build native Components V2 containers.
use panel_container()/reply_embed for embeds that auto-convert via ctx.send."""

from __future__ import annotations

import contextlib

import discord
from discord import ui
from discord.ext.commands import Context

from config import color, emojis


def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def body(*lines: str) -> str:
    parts = []
    for line in lines:
        if not line:
            continue
        for subline in line.split("\n"):
            subline = subline.strip()
            if subline.startswith("> -#"):
                parts.append(subline)
            elif subline.startswith("-#"):
                parts.append(f"> {subline}")
            else:
                parts.append(f"> {subline}")
    return "\n".join(parts)


def caption(text: str) -> str:
    """Small Discord subtext. Idempotent - never stacks ``-# -#``."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    while cleaned.startswith("> -#"):
        cleaned = cleaned[4:].strip()
    while cleaned.startswith("-#"):
        cleaned = cleaned[2:].lstrip()
    return f"-# {cleaned}" if cleaned else ""


def _clean_footer(text: str) -> str:
    cleaned = str(text).strip()
    while cleaned.startswith("> -#"):
        cleaned = cleaned[4:].strip()
    while cleaned.startswith("-#"):
        cleaned = cleaned[2:].lstrip()
    return cleaned


def c2(
    *,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    color: int | None = None,
    accent: int | None = None,
    timestamp: bool = False,
) -> ui.LayoutView:
    """Build a native C2 container.

    Returns a ``ui.LayoutView`` containing a ``ui.Container`` with
    ``TextDisplay`` and ``Separator`` components.

    Parameters
    ----------
    message : str
        Body text. Lines are wrapped in blockquotes unless they contain code fences.
    title : str | None
        Optional title rendered as a ``###`` heading above the body.
    footer : str | None
        Optional footer rendered as ``-#`` subtext below a separator.
    color : int | None
        Kept for call-site compatibility but ignored (C2 containers use ``accent``).
    accent : int | None
        Optional accent colour strip on the left side of the container.
    timestamp : bool
        If True, append an ``-#`` relative timestamp to the footer.
    """
    _ = color
    container = ui.Container()

    if accent is not None:
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, accent)

    raw = str(message or "")
    if "```" in raw:
        content = raw
    else:
        content = body(raw) or raw

    if title:
        content = f"### {title}\n{content}"

    container.add_item(ui.TextDisplay(content))

    has_footer = bool(footer) or timestamp
    if has_footer:
        container.add_item(
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
        )

    footer_parts: list[str] = []
    if footer:
        cleaned = _clean_footer(footer)
        if cleaned:
            footer_parts.append(cleaned)

    if timestamp:
        ts = discord.utils.format_dt(discord.utils.utcnow(), style="R")
        footer_parts.append(ts)

    if footer_parts:
        container.add_item(ui.TextDisplay("-# " + " · ".join(footer_parts)))

    view = ui.LayoutView()
    view.add_item(container)
    return view


def reply_embed(
    *,
    color: int | None = None,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return _reply_embed(color=None, message=message, footer=subtitle, timestamp=False)


def _reply_embed(
    *,
    color: int | None = None,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = False,
) -> discord.Embed:
    """Build a compact embed that auto-converts to C2 via ctx.send.

    Kept as a discord.Embed for interaction response paths that require embeds.
    """
    _ = color
    raw = str(message or "")
    if "```" in raw:
        description = raw
    else:
        description = body(raw) or None
    embed = discord.Embed(description=description)
    embed.color = None
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if footer:
        cleaned = _clean_footer(footer)
        if cleaned:
            embed.set_footer(text=cleaned)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed


def panel_container(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = False,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    _ = color
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(description=description or None, url=url)
    embed.color = None
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


panel_embed = panel_container


class EmbedView(discord.ui.View):
    """embed with a delete button"""

    def __init__(self, ctx: Context, embed: discord.Embed):
        super().__init__(timeout=120.0)
        self.ctx = ctx
        self.embed = embed

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.ctx.author.id:
            await inter.response.send_message(
                embed=reply_embed(
                    color=color.warn,
                    message=(
                        f"{emojis.warn} {inter.user.mention}: "
                        f"Only {self.ctx.author.mention} can use this!"
                    ),
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="delete", style=discord.ButtonStyle.red)
    async def delete(self, inter: discord.Interaction, _: discord.ui.Button):
        await inter.message.delete()
        self.stop()
