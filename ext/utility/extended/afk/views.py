from __future__ import annotations

import math
from typing import Any

import discord
from discord import ui
from discord.utils import format_dt

from core.discord.views.paginate import send_pages, layout_from_items
from core.discord.views.embed import body

from .settings import AFK


def _mention_line(index: int, entry: dict) -> str:
    author_id = entry.get("author_id")
    who = f"<@{author_id}>" if author_id else entry.get("author_name") or "unknown"
    ts = entry.get("timestamp")
    when = format_dt(ts, "R") if ts else "unknown"
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone
        when = format_dt(datetime.fromtimestamp(float(ts), tz=timezone.utc), "R")
    jump = entry.get("jump_url") or ""
    jump_bit = f" · [jump]({jump})" if jump else ""
    return f"-# `{index}.` **{who}** · pinged {when}{jump_bit}"


def build_afk_mention_pages(
    mentions: list[dict],
    *,
    owner_mention: str,
    page_size: int = 10,
) -> list:
    """inrole-style C2 pages for AFK mentions."""
    if not mentions:
        container = ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                try:
                    setattr(container, attr, None)
                except Exception:
                    pass
        container.add_item(ui.TextDisplay(f"**Mentions while AFK**"))
        container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.TextDisplay("-# no mentions recorded for this session"))
        return [layout_from_items([container], timeout=None)]

    # newest first
    ordered = list(reversed(mentions))
    total_pages = max(1, math.ceil(len(ordered) / page_size))
    pages = []
    for page_number, start in enumerate(range(0, len(ordered), page_size), start=1):
        chunk = ordered[start : start + page_size]
        container = ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                try:
                    setattr(container, attr, None)
                except Exception:
                    pass
        container.add_item(ui.TextDisplay(f"**Mentions while AFK** · {owner_mention}"))
        container.add_item(
            ui.TextDisplay(
                f"-# {len(ordered)} mention{'s' if len(ordered) != 1 else ''} · Page {page_number}/{total_pages}"
            )
        )
        container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        lines = [
            _mention_line(i, entry)
            for i, entry in enumerate(chunk, start=start + 1)
        ]
        container.add_item(ui.TextDisplay("\n".join(lines)))
        pages.append(layout_from_items([container], timeout=None))
    return pages


class AFKMentionsButton(ui.View):
    def __init__(self, *, owner_id: int, bot: Any):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.bot = bot

    @ui.button(label="View mentions", style=discord.ButtonStyle.secondary)
    async def view_mentions(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "Only the person who was AFK can view these mentions.",
                ephemeral=True,
            )
        redis = getattr(self.bot, "redis", None)
        if redis is None:
            return await interaction.response.send_message("AFK store unavailable.", ephemeral=True)
        store = AFK(redis)
        mentions = await store.get_mentions(self.owner_id)
        pages = build_afk_mention_pages(
            mentions,
            owner_mention=interaction.user.mention,
        )
        await interaction.response.defer(ephemeral=True)
        # send first page ephemeral-style via followup; paginator needs context-like
        # Fallback: send pages as ephemeral followups with a simple paginator message
        try:
            from core.discord.views.paginate import send_pages
            # build a minimal context shim is hard; send first layout and note
            await interaction.followup.send(view=pages[0], ephemeral=True)
            if len(pages) > 1:
                await interaction.followup.send(
                    f"-# {len(pages)} pages · use `,afk mentions` for the full paginator",
                    ephemeral=True,
                )
        except Exception as exc:
            await interaction.followup.send(f"Couldn't open mentions\n> -# {exc}", ephemeral=True)
