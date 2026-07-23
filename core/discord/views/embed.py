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

def reply_embed(
    *,
    color: int,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return c2(color=color, message=message, footer=subtitle, timestamp=False)



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
