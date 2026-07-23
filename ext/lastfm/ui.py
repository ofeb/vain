from __future__ import annotations

import contextlib

import discord

from core.discord.ctx import Context
from config import color, emojis




def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def c2(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def reply_embed(
    *,
    color: int,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return c2(color=color, message=message, footer=subtitle, timestamp=False)



def build_link_view(*items: tuple[str, str, str | None]) -> discord.ui.View | None:
    view = discord.ui.View(timeout=None)
    for emoji, label, url in items:
        if not url:
            continue
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                emoji=emoji,
                label=label,
                url=url,
            )
        )
    return view if view.children else None


def _warning_embed(user: discord.abc.User, message: str) -> discord.Embed:
    return reply_embed(
        color=color.warn,
        message=f"{emojis.warn} {user.mention}: {message}",
    )


class SkipToPageModal(discord.ui.Modal, title="Skip to page"):
    def __init__(self, view: "LastFMPagedView") -> None:
        super().__init__(timeout=60)
        self.view = view
        self.page = discord.ui.TextInput(
            label="Page number",
            placeholder=f"1-{len(view.pages)}",
            required=True,
            max_length=4,
        )
        self.add_item(self.page)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.page.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message(
                embed=_warning_embed(interaction.user, "Provide a **valid page number**."),
                ephemeral=True,
            )
            return

        page = int(raw)
        if page < 1 or page > len(self.view.pages):
            await interaction.response.send_message(
                embed=_warning_embed(
                    interaction.user,
                    f"Page must be between **1** and **{len(self.view.pages)}**.",
                ),
                ephemeral=True,
            )
            return

        self.view.index = page - 1
        await interaction.response.edit_message(
            embed=self.view.pages[self.view.index],
            view=self.view,
        )


class LastFMPagedView(discord.ui.View):
    def __init__(self, author_id: int, pages: list[discord.Embed]) -> None:
        super().__init__(timeout=60)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self.message: discord.Message | None = None

        if len(self.pages) <= 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True
            self.skip_button.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is not None and interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            embed=_warning_embed(
                interaction.user,
                f"Only <@{self.author_id}> can use these controls!",
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=None)

    @discord.ui.button(
        label="",
        style=discord.ButtonStyle.primary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
    )
    async def prev_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(
            embed=self.pages[self.index],
            view=self,
        )

    @discord.ui.button(
        label="",
        style=discord.ButtonStyle.primary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.next),
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(
            embed=self.pages[self.index],
            view=self,
        )

    @discord.ui.button(
        label="",
        style=discord.ButtonStyle.secondary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.navigate),
    )
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if len(self.pages) <= 1:
            await interaction.response.defer()
            return
        await interaction.response.send_modal(SkipToPageModal(self))

    @discord.ui.button(
        label="",
        style=discord.ButtonStyle.danger,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel),
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.defer()
        if self.message:
            with contextlib.suppress(discord.HTTPException, discord.NotFound):
                await self.message.delete()


async def send_pages(ctx: Context, pages: list[discord.Embed]) -> None:
    if len(pages) <= 1:
        await ctx.send(embed=pages[0] if pages else None)
        return
    view = LastFMPagedView(ctx.author.id, pages)
    view.message = await ctx.send(embed=pages[0], view=view)
