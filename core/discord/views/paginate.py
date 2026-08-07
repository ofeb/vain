from __future__ import annotations

from contextlib import suppress
from typing import Any, Callable, Iterable, List, Sequence, Union

import discord
from discord import ui
from discord.ext.commands import Context

from config import color, emojis

from core.discord.views.embed import reply_embed

Page = Union[discord.Embed, str, ui.Container, Any]


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
    return not text or text in {"​", "‎", "​"}


def embed_to_container(
    embed: discord.Embed,
    *,
    extra_rows: Sequence[ui.ActionRow] | None = None,
    attachment_files: Sequence[discord.File] | None = None,
) -> ui.Container:
    """Convert a rich embed into a Components V2 container with dividers.

    Response containers are always colorless (no accent strip).
    """
    container = ui.Container()

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


def needs_pagination(pages: list[Any]) -> bool:
    return len(pages) > 1


def _warning_embed(user: discord.abc.User, message: str) -> discord.Embed:
    return reply_embed(
        color=color.warn,
        message=f"{emojis.warn} {user.mention}: {message}",
    )


def _emoji(value: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(value)


class PageJumpSelect(ui.LayoutView):
    """Ephemeral C2 select — stays open until timeout; picks update the original message."""

    def __init__(
        self,
        *,
        title: str,
        options: list[discord.SelectOption],
        on_pick: Callable[[discord.Interaction, str], Any],
        author_id: int,
        timeout: float = 180,
        placeholder: str | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.on_pick = on_pick
        self.message: discord.Message | None = None
        self._title = title
        self._options = list(options)[:25]
        self._placeholder = (placeholder or "select a page...").strip()[:150] or "select a page..."
        self._disabled = False
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = ui.Container()
        container.add_item(ui.TextDisplay(self._title))
        row = ui.ActionRow()
        select = ui.Select(
            placeholder=self._placeholder,
            min_values=1,
            max_values=1,
            options=self._options,
            disabled=self._disabled,
        )

        async def _cb(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    embed=_warning_embed(
                        interaction.user,
                        "these controls aren't for you.",
                    ),
                    ephemeral=True,
                )
                return
            if self._disabled:
                await interaction.response.defer()
                return
            value = select.values[0]
            await self.on_pick(interaction, value)

        select.callback = _cb
        row.add_item(select)
        container.add_item(row)
        self.add_item(container)

    async def on_timeout(self) -> None:
        self._disabled = True
        self._build()
        if self.message is not None:
            with suppress(discord.HTTPException):
                await self.message.edit(view=self)



_PAGER_SEARCH = "<:search:1479154501066817600>"
_PAGER_DELETE = "<:delete:1535040504516055191>"


def _strip_trailing_pager(container: ui.Container) -> ui.Container:
    """Drop trailing separator + action-row pager chrome without touching content.

    Safety net when a stored Container was mutated in-place (which stacked buttons).
    Prefer factories that return fresh containers instead.
    """
    children = list(getattr(container, "children", ()) or ())
    if not children:
        return container

    changed = False
    while children and isinstance(children[-1], ui.ActionRow):
        try:
            container.remove_item(children[-1])
        except Exception:
            break
        children.pop()
        changed = True
    if changed and children and isinstance(children[-1], ui.Separator):
        try:
            container.remove_item(children[-1])
        except Exception:
            pass
    return container


def build_pager_row(
    *,
    on_next: Callable,
    on_prev: Callable,
    on_delete: Callable,
    on_search: Callable | None = None,
    show_search: bool = True,
) -> ui.ActionRow:
    """Action row order: forward · delete · backward · search (blue)."""
    row = ui.ActionRow()

    next_btn = ui.Button(
        style=discord.ButtonStyle.secondary,
        emoji=_emoji(emojis.paginator.next),
    )
    del_btn = ui.Button(
        style=discord.ButtonStyle.secondary,
        emoji=_emoji(
            getattr(emojis.paginator, "delete", None)
            or getattr(emojis.paginator, "cancel", None)
            or _PAGER_DELETE
        ),
    )
    prev_btn = ui.Button(
        style=discord.ButtonStyle.secondary,
        emoji=_emoji(emojis.paginator.previous),
    )
    next_btn.callback = on_next
    del_btn.callback = on_delete
    prev_btn.callback = on_prev
    row.add_item(next_btn)
    row.add_item(del_btn)
    row.add_item(prev_btn)

    if show_search and on_search is not None:
        search_btn = ui.Button(
            style=discord.ButtonStyle.primary,
            emoji=_emoji(
                getattr(emojis.paginator, "search", None)
                or getattr(emojis.paginator, "navigate", None)
                or _PAGER_SEARCH
            ),
        )
        search_btn.callback = on_search
        row.add_item(search_btn)

    return row


def _resolve_page(raw: Page) -> Any:
    """Materialize lazy page factories so stored pages are never mutated."""
    if isinstance(raw, (ui.Container, discord.Embed, str)):
        return raw
    if callable(raw):
        try:
            return raw()
        except TypeError:
            return raw
    return raw


class PaginateView(discord.ui.LayoutView):
    """Paginated embeds/containers as Components V2 with shared control order."""

    def __init__(
        self,
        ctx: Context,
        pages: List[Page],
        *,
        timeout: float | None = None,
        start_index: int = 0,
        owner_only: bool = True,
        show_goto: bool = True,
        search_options: list[discord.SelectOption] | None = None,
        search_title: str | None = None,
        search_placeholder: str | None = None,
        on_delete_page: Callable[[int], Any] | None = None,
    ) -> None:
        super().__init__(timeout=timeout if timeout is not None else 180)
        self.ctx = ctx
        self.pages = list(pages)
        self.index = min(max(start_index, 0), max(len(self.pages) - 1, 0))
        self.message: discord.Message | None = None
        self.owner_only = owner_only
        self.show_goto = show_goto
        self.search_options = search_options
        self.search_title = search_title
        self.search_placeholder = search_placeholder
        self.on_delete_page = on_delete_page
        self._rebuild()

    def _as_container(self, raw: Page, *, with_pager: bool = False) -> ui.Container:
        raw = _resolve_page(raw)
        if isinstance(raw, ui.Container):
            
            
            
            container = raw
            if with_pager:
                container = _strip_trailing_pager(raw)
            return container
        if isinstance(raw, discord.Embed):
            return embed_to_container(raw)
        container = ui.Container()
        container.add_item(ui.TextDisplay(str(raw)))
        return container

    def _page_container(self) -> ui.Container:
        
        
        raw = _resolve_page(self.pages[self.index])
        if isinstance(raw, ui.Container):
            container = _strip_trailing_pager(raw)
        else:
            container = self._as_container(raw, with_pager=False)

        if needs_pagination(self.pages):
            container.add_item(ui.Separator(visible=True))
            container.add_item(
                build_pager_row(
                    on_next=self._next,
                    on_prev=self._prev,
                    on_delete=self._cancel,
                    on_search=self._goto if self.show_goto else None,
                    show_search=self.show_goto,
                )
            )
        return container

    def _clear_all(self) -> None:
        """Drop every child. clear_items alone can leave stale C2 nodes on some edits."""
        with suppress(Exception):
            self.clear_items()
        children = list(getattr(self, "children", ()) or ())
        for child in children:
            with suppress(Exception):
                self.remove_item(child)

    def _rebuild(self) -> None:
        self._clear_all()
        if not self.pages:
            empty = ui.Container()
            empty.add_item(ui.TextDisplay("-# nothing left here"))
            self.add_item(empty)
            return
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
        if self.message is None or not self.pages:
            return
        with suppress(discord.HTTPException):
            raw = _resolve_page(self.pages[self.index])
            if isinstance(raw, ui.Container):
                container = _strip_trailing_pager(raw)
            else:
                container = self._as_container(raw, with_pager=False)
            view = ui.LayoutView(timeout=None)
            view.add_item(container)
            await self.message.edit(view=view)

    async def _prev(self, interaction: discord.Interaction) -> None:
        if not self.pages:
            return
        self.index = (self.index - 1) % len(self.pages)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _next(self, interaction: discord.Interaction) -> None:
        if not self.pages:
            return
        self.index = (self.index + 1) % len(self.pages)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _goto(self, interaction: discord.Interaction) -> None:
        if not self.pages:
            await interaction.response.defer()
            return

        if self.search_options:
            options = list(self.search_options)[:25]
            title = self.search_title or (
                f"Search for a page (1-{len(self.pages)}).."
            )
            placeholder = self.search_placeholder or "select a page to jump to..."
        else:
            total = len(self.pages)
            options = [
                discord.SelectOption(
                    label=f"page {i}",
                    value=str(i - 1),
                )
                for i in range(1, min(total, 25) + 1)
            ]
            title = self.search_title or f"Search for a page (1-{total}).."
            placeholder = self.search_placeholder or "select a page to jump to..."

        async def on_pick(inter: discord.Interaction, value: str) -> None:
            try:
                idx = int(value)
            except ValueError:
                idx = 0
            if 0 <= idx < len(self.pages):
                self.index = idx
            
            
            if not inter.response.is_done():
                await inter.response.defer()
            self._rebuild()
            target = self.message
            if target is None and inter.message is not None:
                
                if getattr(inter.message, "flags", None) is not None:
                    try:
                        if not inter.message.flags.ephemeral:
                            target = inter.message
                    except Exception:
                        pass
            if target is not None:
                with suppress(discord.HTTPException):
                    await target.edit(view=self)

        picker = PageJumpSelect(
            title=title,
            options=options,
            on_pick=on_pick,
            author_id=self.ctx.author.id,
            timeout=self.timeout or 180,
            placeholder=placeholder,
        )
        await interaction.response.send_message(view=picker, ephemeral=True)
        with suppress(Exception):
            picker.message = await interaction.original_response()

    async def _cancel(self, interaction: discord.Interaction) -> None:
        if self.on_delete_page is not None and self.pages:
            try:
                await self.on_delete_page(self.index)
            except Exception:
                pass
            if self.pages:
                try:
                    del self.pages[self.index]
                except Exception:
                    pass
            if not self.pages:
                await interaction.response.defer()
                if interaction.message is not None:
                    with suppress(discord.HTTPException):
                        await interaction.message.delete()
                self.stop()
                return
            self.index = min(self.index, len(self.pages) - 1)
            self._rebuild()
            await interaction.response.edit_message(view=self)
            return

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
    search_options: list[discord.SelectOption] | None = None,
    search_title: str | None = None,
    search_placeholder: str | None = None,
    on_delete_page: Callable[[int], Any] | None = None,
) -> discord.Message:
    """send or attach paginated content; skip buttons when there is only one page."""
    pages = list(pages)
    if not pages:
        if message is not None:
            return await message.edit(content="nothing to show", embed=None, view=None)
        return await ctx.send("nothing to show")

    if not needs_pagination(pages) and on_delete_page is None:
        page = pages[0]
        if isinstance(page, ui.Container):
            layout = layout_from_items([page], timeout=timeout)
            if message is not None:
                return await message.edit(view=layout, embed=None, content=None)
            return await ctx.send(view=layout)
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
        search_options=search_options,
        search_title=search_title,
        search_placeholder=search_placeholder,
        on_delete_page=on_delete_page,
    )
    if message is not None:
        return await view.attach(message)
    return await view.start()
