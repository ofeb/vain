from __future__ import annotations

from typing import Any, List, Union

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis


class GoToModal(discord.ui.Modal, title="Skip to Page"):
    response: discord.ui.TextInput = discord.ui.TextInput(
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
            page = int(self.response.value)
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
    def __init__(self, ctx: Context, pages: List[Union[discord.Embed, dict]], timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index == len(self.pages) - 1

    def _get_footer_suffix(self, embed: discord.Embed) -> str:
        total = len(self.pages)
        current = self.index + 1
        return f"Page {current}/{total} ({total} entry{'s' if total != 1 else ''})"

    def _current(self) -> dict:
        raw = self.pages[self.index]
        base: dict[str, Any] = {"view": self}
        if isinstance(raw, discord.Embed):
            footer_text = raw.footer.text if raw.footer else ""
            page_info = self._get_footer_suffix(raw)
            if footer_text:
                raw.set_footer(text=f"{footer_text} ∙ {page_info}")
            else:
                raw.set_footer(text=page_info)
            return {**base, "embed": raw}
        return {**base, "content": str(raw)}

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
        if self.message:
            await self.message.edit(**self._current())
        else:
            await inter.edit_original_message(**self._current())

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel))
    async def cancel_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await inter.response.edit_message(view=self)
        self.stop()

    async def start(self) -> discord.Message:
        msg = await self.ctx.send(**self._current())
        self.message = msg
        return msg
