from __future__ import annotations

from contextlib import suppress
from typing import Any, List, Union

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis

Page = Union[discord.Embed, str]


def needs_pagination(pages: list[Page]) -> bool:
    return len(pages) > 1


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
        pages: List[Page],
        *,
        timeout: float | None = None,
        start_index: int = 0,
        owner_only: bool = True,
    ) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = min(max(start_index, 0), max(len(self.pages) - 1, 0))
        self.message: discord.Message | None = None
        self.owner_only = owner_only

    def _current(self) -> dict[str, Any]:
        raw = self.pages[self.index]
        payload: dict[str, Any] = {"view": self if needs_pagination(self.pages) else None}
        if isinstance(raw, discord.Embed):
            payload["embed"] = raw
            payload["content"] = None
        else:
            payload["content"] = str(raw)
            payload["embed"] = None
        return payload

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.owner_only or interaction.user.id == self.ctx.author.id:
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
        style=discord.ButtonStyle.primary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
    )
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(**self._current())

    @discord.ui.button(
        style=discord.ButtonStyle.primary,
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
        if not self.pages:
            self.message = await self.ctx.send("nothing to show")
            return self.message
        payload = self._current()
        if not needs_pagination(self.pages):
            payload.pop("view", None)
        self.message = await self.ctx.send(**payload)
        return self.message

    async def attach(self, message: discord.Message) -> discord.Message:
        payload = self._current()
        if not needs_pagination(self.pages):
            payload["view"] = None
        self.message = await message.edit(**payload)
        return self.message


async def send_pages(
    ctx: Context,
    pages: List[Page],
    *,
    message: discord.Message | None = None,
    start_index: int = 0,
    owner_only: bool = True,
    timeout: float | None = None,
) -> discord.Message:
    """send or attach paginated embeds; skip buttons when there is only one page."""
    pages = list(pages)
    if not pages:
        if message is not None:
            return await message.edit(content="nothing to show", embed=None, view=None)
        return await ctx.send("nothing to show")

    if not needs_pagination(pages):
        page = pages[0]
        payload: dict[str, Any] = {"view": None}
        if isinstance(page, discord.Embed):
            payload["embed"] = page
            payload["content"] = None
        else:
            payload["content"] = str(page)
            payload["embed"] = None
        if message is not None:
            return await message.edit(**payload)
        return await ctx.send(**payload)

    view = PaginateView(
        ctx,
        pages,
        timeout=timeout,
        start_index=start_index,
        owner_only=owner_only,
    )
    if message is not None:
        return await view.attach(message)
    return await view.start()
