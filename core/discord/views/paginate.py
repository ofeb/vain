"""Paginated list view with bleed-style navigation controls."""

from __future__ import annotations

from typing import List, Union

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis


class PageModal(discord.ui.Modal, title="Skip to Page"):
    page: discord.ui.TextInput = discord.ui.TextInput(
        label="Page Number",
        placeholder="Enter a page number...",
        min_length=1,
        max_length=4,
        required=True,
    )

    def __init__(self, view: PaginateView) -> None:
        super().__init__()
        self._v = view

    async def on_submit(self, inter: discord.Interaction) -> None:
        try:
            page = int(self.page.value)
        except ValueError:
            embed = discord.Embed(
                color=color.deny,
                description=f"{emojis.deny} {inter.user.mention}: That's not a valid page number.",
            )
            await inter.response.send_message(embed=embed, ephemeral=True)
            return

        if page < 1 or page > len(self._v.pages):
            embed = discord.Embed(
                color=color.deny,
                description=f"{emojis.deny} {inter.user.mention}: Page must be between **1** and **{len(self._v.pages)}**.",
            )
            await inter.response.send_message(embed=embed, ephemeral=True)
            return

        self._v.index = page - 1
        self._v._update_buttons()
        await inter.response.edit_message(**self._v._current())


class PaginateView(discord.ui.View):
    """navigate through a list of pages"""

    def __init__(self, ctx: Context, pages: List[Union[discord.Embed, str]], timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
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
        if inter.user.id == self.ctx.author.id:
            return True
        await inter.response.send_message("not yours", ephemeral=True)
        return False

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(emojis.paginator.previous))
    async def prev_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await inter.response.edit_message(**self._current())

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(emojis.paginator.next))
    async def next_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await inter.response.edit_message(**self._current())

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(emojis.paginator.navigate))
    async def goto_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        embed = discord.Embed(
            color=color.dark,
            description="🔢 What page would you like to skip to?",
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

        try:
            response: discord.Message = await self.ctx.bot.wait_for(
                "message",
                check=lambda m: m.author.id == inter.user.id and m.channel.id == inter.channel_id,
                timeout=30.0,
            )
        except TimeoutError:
            return

        try:
            page = int(response.content.strip())
        except ValueError:
            fail_embed = discord.Embed(
                color=color.deny,
                description=f"{emojis.deny} {inter.user.mention}: That's not a valid page number.",
            )
            await inter.edit_original_response(embed=fail_embed)
            return

        if page < 1 or page > len(self.pages):
            fail_embed = discord.Embed(
                color=color.deny,
                description=f"{emojis.deny} {inter.user.mention}: Page must be between **1** and **{len(self.pages)}**.",
            )
            await inter.edit_original_response(embed=fail_embed)
            return

        self.index = page - 1
        self._update_buttons()
        await inter.edit_original_response(embed=None, content=None)
        await self.message.edit(**self._current())

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel))
    async def cancel_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await inter.response.edit_message(view=self)
        self.stop()

    async def start(self) -> discord.Message:
        """send first page and start listening"""
        msg = await self.ctx.send(**self._current())
        self.message = msg
        return msg
