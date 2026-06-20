from __future__ import annotations

from contextlib import suppress
from typing import Any, List, Union

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis


def _warning_embed(user: discord.abc.User, message: str) -> discord.Embed:
    return discord.Embed(
        color=color.warn,
        description=f"{emojis.warn} {user.mention}: {message}",
    )


class SkipToPageModal(discord.ui.Modal, title="Skip to page"):
    def __init__(self, pager: "PaginateView") -> None:
        super().__init__(timeout=60)
        self.pager = pager
        self.page = discord.ui.TextInput(
            label="Page number",
            placeholder=f"1-{len(pager.pages)}",
            required=True,
            max_length=4,
        )
        self.add_item(self.page)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.page.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message(
                embed=_warning_embed(
                    interaction.user,
                    "Provide a **valid page number**.",
                ),
                ephemeral=True,
            )
            return

        page_number = int(raw)
        if page_number < 1 or page_number > len(self.pager.pages):
            await interaction.response.send_message(
                embed=_warning_embed(
                    interaction.user,
                    "That page is **out of range**.",
                ),
                ephemeral=True,
            )
            return

        self.pager.index = page_number - 1
        await interaction.response.edit_message(**self.pager._current())


class PaginateView(discord.ui.View):
    def __init__(
        self,
        ctx: Context,
        pages: List[Union[discord.Embed, str]],
        *,
        timeout: float = 60.0,
        start_index: int = 0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = min(max(start_index, 0), max(len(self.pages) - 1, 0))
        self.message: discord.Message | None = None

    def _current(self) -> dict[str, Any]:
        raw = self.pages[self.index]
        payload: dict[str, Any] = {"view": self}
        if isinstance(raw, discord.Embed):
            payload["embed"] = raw
        else:
            payload["content"] = str(raw)
        return payload

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message(
            embed=_warning_embed(
                interaction.user,
                "You're not the **author** of this embed!",
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        with suppress(discord.HTTPException):
            await self.message.edit(view=None)

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
    )
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(**self._current())

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.next),
    )
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(**self._current())

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.navigate),
    )
    async def goto_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(SkipToPageModal(self))

    @discord.ui.button(
        style=discord.ButtonStyle.danger,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel),
    )
    async def cancel_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        if interaction.message is not None:
            with suppress(discord.HTTPException):
                await interaction.message.delete()
        self.stop()

    async def start(self) -> discord.Message:
        self.message = await self.ctx.send(**self._current())
        return self.message
