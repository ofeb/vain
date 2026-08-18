"""embed display view with delete button.
simple view wrapper around a discord embed.
use EmbedView to send embeds with a trash button"""

import discord
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


def c2(
    *,
    color: int | None = None,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = False,
) -> discord.Embed:
    """Build a compact embed that converts to a C2 lookalike on send.

    No embed colour - C2 containers render without an accent strip.
    ``color`` is accepted for call-site compatibility and ignored.
    Footer is set via ``set_footer`` so embed_to_layout inserts a divider
    between the body and the ``-#`` footer line.
    Code fences are left unwrapped so OCR/transcribe bodies stay intact.
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
        cleaned = str(footer).strip()
        while cleaned.startswith("> -#"):
            cleaned = cleaned[4:].strip()
        while cleaned.startswith("-#"):
            cleaned = cleaned[2:].lstrip()
        if cleaned:
            embed.set_footer(text=cleaned)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed


def reply_embed(
    *,
    color: int | None = None,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return c2(color=None, message=message, footer=subtitle, timestamp=False)


def panel_embed(
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
