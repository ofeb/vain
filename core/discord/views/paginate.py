"""Paginated list view with bleed-style navigation controls."""

from __future__ import annotations

from typing import List, Union

import discord
from discord.ext.commands import Context

from core.managers.values import emojis


class PaginateView(discord.ui.View):
    """navigate through a list of pages"""

    def __init__(self, ctx: Context, pages: List[Union[discord.Embed, str]], timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
        self.prev_btn.label = None
        self.next_btn.label = None
        self.prev_btn.emoji = discord.PartialEmoji.from_str(emojis.paginator.previous)
        self.next_btn.emoji = discord.PartialEmoji.from_str(emojis.paginator.next)
        self.prev_btn.style = discord.ButtonStyle.secondary
        self.next_btn.style = discord.ButtonStyle.secondary
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index == len(self.pages) - 1

    def _current(self) -> dict:
        p = self.pages[self.index]
        base = {"view": self}
        if isinstance(p, discord.Embed):
            return {**base, "embed": p}
        return {**base, "content": str(p)}

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.ctx.author.id:
            await inter.response.send_message("not yours", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def prev_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await inter.response.edit_message(**self._current())

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def next_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await inter.response.edit_message(**self._current())

    async def start(self) -> discord.Message:
        """send first page and start listening"""
        return await self.ctx.send(**self._current())
