"""yes no confirmation view component.
sends a message and waits for user to click yes or no.
use ConfirmView in commands that need confirmation"""

import discord
from discord.ext.commands import Context


class ConfirmView(discord.ui.View):
    """two button confirm or cancel view"""

    def __init__(
        self,
        ctx: Context,
        *,
        member=None,
        timeout: float = 30.0,
    ):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.member = member or ctx.author
        self.value: bool = None

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.member.id:
            await inter.response.send_message(
                f"Only {self.member.mention} can use this.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="confirm", style=discord.ButtonStyle.green)
    async def confirm(self, inter: discord.Interaction, _: discord.ui.Button):
        self.value = True
        await inter.response.defer()
        self.stop()

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.red)
    async def cancel(self, inter: discord.Interaction, _: discord.ui.Button):
        self.value = False
        await inter.response.defer()
        self.stop()

    async def prompt(self, message: str) -> bool:
        """send message and wait for yes or no"""
        msg = await self.ctx.send(message, view=self)
        await self.wait()
        await msg.delete()
        return bool(self.value)
