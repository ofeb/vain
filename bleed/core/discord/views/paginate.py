"""paginated list view with nav buttons.
shows one page at a time with forward and back buttons.
use PaginateView with a list of embeds or strings"""

import discord
from discord.ext.commands import Context
from typing import List, Union


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
            p.set_footer(text=f"page {self.index+1} of {len(self.pages)}")
            return {**base, "embed": p}
        return {**base, "content": f"{p}\npage {self.index+1}/{len(self.pages)}"}

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.ctx.author.id:
            await inter.response.send_message("not yours", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="<", style=discord.ButtonStyle.blurple)
    async def prev_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await inter.response.edit_message(**self._current())

    @discord.ui.button(label=">", style=discord.ButtonStyle.blurple)
    async def next_btn(self, inter: discord.Interaction, _: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await inter.response.edit_message(**self._current())

    async def start(self) -> discord.Message:
        """send first page and start listening"""
        return await self.ctx.send(**self._current())
