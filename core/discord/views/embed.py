"""embed display view with delete button.
simple view wrapper around a discord embed.
use EmbedView to send embeds with a trash button"""

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis


class EmbedView(discord.ui.View):
    """embed with a delete button"""

    def __init__(self, ctx: Context, embed: discord.Embed):
        super().__init__(timeout=120.0)
        self.ctx = ctx
        self.embed = embed

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.ctx.author.id:
            await inter.response.send_message(
                embed=discord.Embed(
                    color=color.warn,
                    description=(
                        f"{emojis.warn} {inter.user.mention}: "
                        "You're not the **author** of this embed!"
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
