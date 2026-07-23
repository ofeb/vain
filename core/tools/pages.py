from __future__ import annotations

import inspect
from typing import Iterable, Sequence

import discord

from core.discord.views.paginate import PaginateView, needs_pagination, send_pages


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
        timeout: float | None = None,
        start_index: int = 0,
        owner_only: bool = True,
        show_goto: bool = True,
        **kwargs,
    ) -> None:
        if isinstance(pages, list):
            self.pages = pages
        else:
            self.pages = list(pages)
        self.ctx = ctx
        self.timeout = timeout
        self.start_index = start_index
        self.owner_only = owner_only
        self.show_goto = show_goto
        self.kwargs = kwargs
        self.message: discord.Message | None = None

    async def start(self) -> discord.Message:
        
        kwargs = {
            "start_index": self.start_index,
            "owner_only": self.owner_only,
            "timeout": self.timeout,
            "show_goto": self.show_goto,
        }
        try:
            params = inspect.signature(send_pages).parameters
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
                filtered = kwargs
            else:
                filtered = {k: v for k, v in kwargs.items() if k in params}
        except (TypeError, ValueError):
            filtered = {
                k: v
                for k, v in kwargs.items()
                if k in {"start_index", "owner_only", "timeout"}
            }

        
        if not self.show_goto and "show_goto" not in filtered:
            try:
                view_kwargs = {
                    "timeout": self.timeout,
                    "start_index": self.start_index,
                    "owner_only": self.owner_only,
                    "show_goto": False,
                }
                try:
                    vparams = inspect.signature(PaginateView.__init__).parameters
                    if not any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in vparams.values()
                    ):
                        view_kwargs = {k: v for k, v in view_kwargs.items() if k in vparams}
                except (TypeError, ValueError):
                    view_kwargs = {
                        "timeout": self.timeout,
                        "start_index": self.start_index,
                        "owner_only": self.owner_only,
                    }
                view = PaginateView(self.ctx, list(self.pages), **view_kwargs)
                
                if hasattr(view, "show_goto"):
                    view.show_goto = False
                    if hasattr(view, "_rebuild"):
                        view._rebuild()
                self.message = await view.start()
                return self.message
            except TypeError:
                pass

        self.message = await send_pages(self.ctx, self.pages, **filtered)
        return self.message
