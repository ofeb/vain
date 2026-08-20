"""Two-button "would you rather" poll view (used in DMs/group chats).

Guilds use reactions instead; this view is for contexts where reactions
cannot be added (no ``me`` / no Add Reactions permission).
"""

from __future__ import annotations

import contextlib

import discord

from config import color

from core.discord.ctx import Context
from core.discord.views.embed import body, compose, panel_container


class WyrView(discord.ui.View):
    """Two-button would-you-rather poll (invoker-only)."""

    def __init__(
        self,
        ctx: Context,
        option1: str,
        option2: str,
        *,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.option1 = option1
        self.option2 = option2
        self.message: discord.Message | None = None

        for index, option in enumerate((option1, option2), start=1):
            button = discord.ui.Button(
                label=f"Option {index}",
                style=discord.ButtonStyle.primary,
                custom_id=f"wyr:{index}",
            )
            button.callback = self._make_callback(index, option)  # type: ignore[method-assign]
            self.add_item(button)

    def _make_callback(self, index: int, option: str):
        async def callback(inter: discord.Interaction) -> None:
            if inter.user.id != self.ctx.author.id:
                await inter.response.send_message(
                    "Only the person who started the poll can vote.",
                    ephemeral=True,
                )
                return
            for item in self.children:
                item.disabled = True
            embed = panel_container(
                title="Would You Rather?",
                color=color.base,
                lines=[f"**1:** {self.option1}", f"**2:** {self.option2}", f"{self.ctx.author.mention} chose **{option}**"],
            )
            await inter.response.edit_message(embed=embed, view=self)
            self.stop()

        return callback

    async def on_timeout(self) -> None:
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=None)
