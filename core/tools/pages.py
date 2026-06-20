from __future__ import annotations

from typing import Iterable, Sequence

import discord

from core.discord.views.paginate import PaginateView


def _copy_embed(embed: discord.Embed) -> discord.Embed:
    return discord.Embed.from_dict(embed.to_dict())


def _entry_label(total: int) -> str:
    return "entry" if total == 1 else "entries"


def build_pages(
    embed: discord.Embed,
    lines: Sequence[str] | Iterable[str],
    *,
    split: int = 10,
) -> list[discord.Embed]:
    entries = [str(line) for line in lines]
    if not entries:
        return [_copy_embed(embed)]

    chunks = [entries[index : index + split] for index in range(0, len(entries), split)]
    total = len(chunks)
    pages: list[discord.Embed] = []

    for index, chunk in enumerate(chunks, start=1):
        page = _copy_embed(embed)
        body = "\n".join(chunk)
        page.description = "\n\n".join(
            piece for piece in (page.description, body) if piece
        ).strip()
        original_footer = page.footer.text if page.footer else None
        footer = f"Page {index}/{total} ({len(entries)} {_entry_label(len(entries))})"
        if original_footer:
            footer = f"{original_footer} • {footer}"
        icon_url = page.footer.icon_url if page.footer else None
        page.set_footer(text=footer, icon_url=icon_url)
        pages.append(page)

    return pages


class Paginator:
    """compat wrapper around the current paginate view."""

    def __init__(
        self,
        ctx,
        pages: Sequence[discord.Embed | str] | Iterable[discord.Embed | str],
        *,
        timeout: float = 60.0,
        start_index: int = 0,
        **kwargs,
    ) -> None:
        if isinstance(pages, list):
            self.pages = pages
        else:
            self.pages = list(pages)
        self.ctx = ctx
        self.timeout = timeout
        self.start_index = start_index
        self.kwargs = kwargs
        self.message: discord.Message | None = None

    async def start(self) -> discord.Message:
        if not self.pages:
            self.message = await self.ctx.search("nothing to show")
            return self.message

        if len(self.pages) == 1:
            page = self.pages[0]
            payload = {"embed": page} if isinstance(page, discord.Embed) else {
                "content": str(page)
            }
            self.message = await self.ctx.send(**payload)
            return self.message

        view = PaginateView(
            self.ctx,
            self.pages,
            timeout=self.timeout,
            start_index=self.start_index,
        )
        self.message = await view.start()
        return self.message
