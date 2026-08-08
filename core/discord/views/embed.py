"""embed display view with delete button.
simple view wrapper around a discord embed.
use EmbedView to send embeds with a trash button"""

import discord
from discord.ext.commands import Context

from config import color, emojis


def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)


def caption(text: str) -> str:
    """Small Discord subtext. Idempotent — never stacks ``-# -#``."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    
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
    timestamp: bool = True,
) -> discord.Embed:
    """Build a compact embed that converts to a C2 lookalike on send.

    No embed colour — C2 containers render without an accent strip.
    ``color`` is accepted for call-site compatibility and ignored.
    """
    _ = color
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
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
    timestamp: bool = True,
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
