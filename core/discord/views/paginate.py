from __future__ import annotations

from contextlib import suppress
from typing import Any, List, Union

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis
from core.tools.aesthetic import embed_to_container, reply_embed

Page = Union[discord.Embed, str]


def needs_pagination(pages: list[Page]) -> bool:
    return len(pages) > 1


def _warning_embed(user: discord.abc.User, message: str) -> discord.Embed:
    return reply_embed(
        color=color.warn,
        message=f"{emojis.warn} {user.mention}: {message}",
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
        self.pager._rebuild()
        await interaction.response.edit_message(view=self.pager)


class PaginateView(discord.ui.LayoutView):
    """Paginated embeds as Components V2 containers with divider layout."""

    def __init__(
        self,
        ctx: Context,
        pages: List[Page],
        *,
        timeout: float | None = None,
        start_index: int = 0,
        owner_only: bool = True,
    ) -> None:
        super().__init__(timeout=timeout if timeout is not None else 180)
        self.ctx = ctx
        self.pages = pages
        self.index = min(max(start_index, 0), max(len(self.pages) - 1, 0))
        self.message: discord.Message | None = None
        self.owner_only = owner_only
        self._rebuild()

    def _page_container(self) -> discord.ui.Container:
        raw = self.pages[self.index]
        if isinstance(raw, discord.Embed):
            container = embed_to_container(raw)
        else:
            accent = getattr(self.ctx.bot, "color", None) or 0x5865F2
            container = discord.ui.Container(accent_colour=accent)
            container.add_item(discord.ui.TextDisplay(str(raw)))

        if needs_pagination(self.pages):
            container.add_item(discord.ui.Separator(visible=True))
            row = discord.ui.ActionRow()
            prev_btn = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
            )
            next_btn = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.next),
            )
            goto_btn = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.navigate),
            )
            cancel_btn = discord.ui.Button(
                style=discord.ButtonStyle.danger,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel),
            )
            prev_btn.callback = self._prev
            next_btn.callback = self._next
            goto_btn.callback = self._goto
            cancel_btn.callback = self._cancel
            row.add_item(prev_btn)
            row.add_item(next_btn)
            row.add_item(goto_btn)
            row.add_item(cancel_btn)
            container.add_item(row)
            # page footer hint
            container.add_item(
                discord.ui.TextDisplay(
                    f"-# Page {self.index + 1}/{len(self.pages)}"
                )
            )
        return container

    def _rebuild(self) -> None:
        self.clear_items()
        self.add_item(self._page_container())

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
            # Drop interactive controls on timeout
            raw = self.pages[self.index]
            if isinstance(raw, discord.Embed):
                container = embed_to_container(raw)
            else:
                accent = getattr(self.ctx.bot, "color", None) or 0x5865F2
                container = discord.ui.Container(accent_colour=accent)
                container.add_item(discord.ui.TextDisplay(str(raw)))
            view = discord.ui.LayoutView(timeout=None)
            view.add_item(container)
            await self.message.edit(view=view)

    async def _prev(self, interaction: discord.Interaction) -> None:
        self.index = (self.index - 1) % len(self.pages)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _next(self, interaction: discord.Interaction) -> None:
        self.index = (self.index + 1) % len(self.pages)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _goto(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SkipToPageModal(self))

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.message is not None:
            with suppress(discord.HTTPException):
                await interaction.message.delete()
        self.stop()

    async def start(self) -> discord.Message:
        if not self.pages:
            self.message = await self.ctx.send("nothing to show")
            return self.message
        self._rebuild()
        self.message = await self.ctx.send(view=self)
        return self.message

    async def attach(self, message: discord.Message) -> discord.Message:
        self._rebuild()
        self.message = await message.edit(view=self, embed=None, content=None)
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
        if isinstance(page, discord.Embed):
            if message is not None:
                # Prefer container edit when possible
                from core.tools.aesthetic import embed_to_layout

                layout = embed_to_layout(page)
                return await message.edit(view=layout, embed=None, content=None)
            return await ctx.send(embed=page)
        if message is not None:
            return await message.edit(content=str(page), embed=None, view=None)
        return await ctx.send(str(page))

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
