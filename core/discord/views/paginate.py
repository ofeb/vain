from __future__ import annotations

from contextlib import suppress
from typing import Any, Iterable, List, Sequence, Union

import discord
from discord import ui
from discord.ext.commands import Context

from config import color, emojis



def _accent_from_embed(embed: discord.Embed) -> int | None:
    colour = embed.colour or embed.color
    if colour is None:
        return None
    try:
        return int(colour.value)
    except Exception:
        return None

def _blankish(value: str | None) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text in {"\u200b", "‎", "​"}

def embed_to_container(
    embed: discord.Embed,
    *,
    extra_rows: Sequence[ui.ActionRow] | None = None,
    attachment_files: Sequence[discord.File] | None = None,
) -> ui.Container:
    """Convert a rich embed into a Components V2 container with dividers."""
    accent = _accent_from_embed(embed)
    container = ui.Container(accent_colour=accent)

    
    author_name = embed.author.name if embed.author else None
    author_icon = embed.author.icon_url if embed.author else None
    thumb = embed.thumbnail.url if embed.thumbnail else None
    title = embed.title
    if title and embed.url:
        title_md = f"### [{title}]({embed.url})"
    elif title:
        title_md = f"### {title}"
    else:
        title_md = None

    header_bits: list[str] = []
    if author_name and not _blankish(author_name):
        header_bits.append(f"**{author_name}**")
    if title_md:
        header_bits.append(title_md)

    media_url = thumb or author_icon
    has_body = bool(embed.description and not _blankish(embed.description))
    has_fields = bool(embed.fields)
    image_url = embed.image.url if embed.image else None
    has_footer = bool(embed.footer and not _blankish(getattr(embed.footer, "text", None)))
    has_ts = bool(embed.timestamp)

    if header_bits and media_url:
        try:
            container.add_item(
                ui.Section(
                    ui.TextDisplay("\n".join(header_bits)),
                    accessory=ui.Thumbnail(media=str(media_url)),
                )
            )
        except Exception:
            container.add_item(ui.TextDisplay("\n".join(header_bits)))
    elif header_bits:
        container.add_item(ui.TextDisplay("\n".join(header_bits)))

    def _sep() -> None:
        container.add_item(ui.Separator(visible=True))

    added_content = bool(header_bits)

    if has_body:
        if added_content:
            _sep()
        container.add_item(ui.TextDisplay(str(embed.description)))
        added_content = True

    if has_fields:
        field_chunks: list[str] = []
        for field in embed.fields:
            name = "" if _blankish(field.name) else str(field.name)
            value = "" if _blankish(field.value) else str(field.value)
            if name and value:
                field_chunks.append(f"**{name}**\n{value}")
            elif value:
                field_chunks.append(value)
            elif name:
                field_chunks.append(f"**{name}**")
        if field_chunks:
            if added_content:
                _sep()
            container.add_item(ui.TextDisplay("\n\n".join(field_chunks)))
            added_content = True

    if image_url:
        if added_content:
            _sep()
        try:
            if str(image_url).startswith("attachment://") and attachment_files:
                fname = str(image_url).split("attachment://", 1)[-1]
                match = next((f for f in attachment_files if f.filename == fname), None)
                if match is not None:
                    container.add_item(ui.MediaGallery(discord.MediaGalleryItem(match)))
                else:
                    container.add_item(
                        ui.MediaGallery(discord.MediaGalleryItem(str(image_url)))
                    )
            else:
                container.add_item(
                    ui.MediaGallery(discord.MediaGalleryItem(str(image_url)))
                )
        except Exception:
            container.add_item(ui.TextDisplay(f"[image]({image_url})"))
        added_content = True

    if attachment_files and not image_url:
        for f in attachment_files[:1]:
            try:
                if added_content:
                    _sep()
                container.add_item(ui.File(f))
                added_content = True
            except Exception:
                pass

    if has_footer or has_ts:
        if added_content:
            _sep()
        footer = ""
        if has_footer:
            footer = str(embed.footer.text)
        if has_ts:
            try:
                ts = f"<t:{int(embed.timestamp.timestamp())}:R>"
                footer = f"{footer} · {ts}" if footer else ts
            except Exception:
                pass
        if footer:
            container.add_item(ui.TextDisplay(f"-# {footer}"))
        added_content = True

    if extra_rows:
        if added_content:
            _sep()
        for row in extra_rows:
            container.add_item(row)

    return container

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

def _link_buttons_from_view(view: ui.View | None) -> list[ui.Button]:
    if view is None or isinstance(view, ui.LayoutView):
        return []
    out: list[ui.Button] = []
    for child in getattr(view, "children", ()) or ():
        if isinstance(child, ui.Button) and getattr(child, "url", None):
            out.append(
                ui.Button(
                    style=child.style or discord.ButtonStyle.link,
                    label=child.label,
                    url=child.url,
                    emoji=child.emoji,
                    disabled=child.disabled,
                )
            )
    return out

def layout_from_items(
    items: Iterable[ui.Item],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    layout = ui.LayoutView(timeout=timeout)
    for item in items:
        layout.add_item(item)
    return layout

def embed_to_layout(
    embed: discord.Embed,
    *,
    view: ui.View | None = None,
    attachment_files: Sequence[discord.File] | None = None,
    timeout: float | None = 180,
) -> ui.LayoutView:
    link_buttons = _link_buttons_from_view(view)
    extra_rows: list[ui.ActionRow] = []
    if link_buttons:
        
        for i in range(0, len(link_buttons), 5):
            row = ui.ActionRow(*link_buttons[i : i + 5])
            extra_rows.append(row)
    container = embed_to_container(
        embed,
        extra_rows=extra_rows or None,
        attachment_files=attachment_files,
    )
    return layout_from_items([container], timeout=timeout)



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
        show_goto: bool = True,
    ) -> None:
        super().__init__(timeout=timeout if timeout is not None else 180)
        self.ctx = ctx
        self.pages = pages
        self.index = min(max(start_index, 0), max(len(self.pages) - 1, 0))
        self.message: discord.Message | None = None
        self.owner_only = owner_only
        self.show_goto = show_goto
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
            cancel_btn = discord.ui.Button(
                style=discord.ButtonStyle.danger,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel),
            )
            prev_btn.callback = self._prev
            next_btn.callback = self._next
            cancel_btn.callback = self._cancel
            row.add_item(prev_btn)
            row.add_item(next_btn)
            if self.show_goto:
                goto_btn = discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    emoji=discord.PartialEmoji.from_str(emojis.paginator.navigate),
                )
                goto_btn.callback = self._goto
                row.add_item(goto_btn)
            row.add_item(cancel_btn)
            container.add_item(row)
            
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
                f"Only {self.ctx.author.mention} can use these controls!",
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        with suppress(discord.HTTPException):
            
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
    show_goto: bool = True,
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
        show_goto=show_goto,
    )
    if message is not None:
        return await view.attach(message)
    return await view.start()
