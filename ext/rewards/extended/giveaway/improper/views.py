"""Components V2 giveaway panels and entry views."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord import ui

from config import color


def _ends_line(end_time: datetime | None) -> str:
    if end_time is None:
        return "**Ends** soon"
    rel = discord.utils.format_dt(end_time, style="R")
    abs_ = discord.utils.format_dt(end_time, style="f")
    return f"**Ends** {rel} ({abs_})"


def build_giveaway_panel(
    *,
    message_id: int,
    prize: str,
    end_time: datetime | None,
    winners: int,
    host_mention: str,
    entries: int,
    guild_icon: str | None = None,
    ended: bool = False,
    winner_mentions: str | None = None,
    no_entries: bool = False,
    accent: int | None = None,
    button_label: str | None = None,
    button_emoji: str | None = None,
    show_entries: bool = True,
    join_type: str = "button",
    custom_body: str | None = None,
    requirement_lines: list[str] | None = None,
) -> ui.LayoutView:
    """Active / ended giveaway panel matching the inspo Components V2 layout."""
    prize = (prize or "Giveaway").strip() or "Giveaway"
    accent = int(accent if accent is not None else color.base)
    layout = ui.LayoutView(timeout=None)
    container = ui.Container()
    _ = accent

    req_block = ""
    if requirement_lines:
        bullets = "\n".join(f"> -# · {line}" for line in requirement_lines)
        req_block = f"\n**To enter**\n{bullets}"

    if custom_body:
        body = custom_body
        if req_block and "To enter" not in body:
            body = f"{body.rstrip()}{req_block}"
    elif ended:
        if no_entries:
            body = (
                f"## {prize}\n"
                f"**Entries** {entries}\n"
                f"> -# ended · **no valid entries**\n"
                f"> -# hosted by {host_mention}"
            )
        else:
            wlabel = "Winner" if (winner_mentions or "").count("<@") <= 1 else "Winners"
            body = (
                f"## {prize}\n"
                f"**{wlabel}** {winner_mentions or '-'}\n"
                f"**Entries** {entries}\n"
                f"> -# ended · hosted by {host_mention}"
            )
    else:
        entries_bit = f"  **Entries** {entries}" if show_entries else ""
        body = (
            f"## {prize}\n"
            f"{_ends_line(end_time)}\n"
            f"**Winners** {winners}{entries_bit}"
            f"{req_block}\n"
            f"> -# hosted by {host_mention}"
        )

    if guild_icon:
        try:
            container.add_item(
                ui.Section(
                    ui.TextDisplay(body),
                    accessory=ui.Thumbnail(media=str(guild_icon)),
                )
            )
        except Exception:
            container.add_item(ui.TextDisplay(body))
    else:
        container.add_item(ui.TextDisplay(body))

    container.add_item(ui.Separator(visible=True))

    row = ui.ActionRow()
    join_type = (join_type or "button").lower()
    if not ended and join_type != "reaction":
        label = (button_label or "Enter").strip() or "Enter"
        if show_entries:
            label = f"{label}  ({entries})"
        emoji = (button_emoji or "🎉").strip() or "🎉"
        try:
            row.add_item(
                ui.Button(
                    style=discord.ButtonStyle.secondary,
                    emoji=emoji,
                    label=label[:80],
                    custom_id=f"gw:enter:{message_id}",
                )
            )
        except Exception:
            row.add_item(
                ui.Button(
                    style=discord.ButtonStyle.secondary,
                    emoji="🎉",
                    label=label[:80],
                    custom_id=f"gw:enter:{message_id}",
                )
            )
    if show_entries:
        row.add_item(
            ui.Button(
                style=discord.ButtonStyle.secondary,
                label="View Entries",
                custom_id=f"gw:entries:{message_id}",
            )
        )
    if row.children:
        container.add_item(row)
    layout.add_item(container)
    return layout


def build_win_announce_panel(
    *,
    prize: str,
    winner_mentions: str,
    host_mention: str | None = None,
    reroll: bool = False,
    accent: int | None = None,
) -> ui.LayoutView:
    """Channel fallback / reply announce: user won (Components V2)."""
    prize = (prize or "Giveaway").strip() or "Giveaway"
    accent = int(accent if accent is not None else color.base)
    layout = ui.LayoutView(timeout=None)
    container = ui.Container()
    _ = accent
    verb = "rerolled and won" if reroll else "won"
    host_line = f"\n> -# Hosted by {host_mention}" if host_mention else ""
    container.add_item(
        ui.TextDisplay(
            f"**{winner_mentions}** {verb} **{prize}**\n"
            f"> -# congratulations · enjoy your prize{host_line}"
        )
    )
    layout.add_item(container)
    return layout


def build_dm_win_view(jump_url: str | None) -> ui.View | None:
    if not jump_url:
        return None
    view = ui.View(timeout=None)
    view.add_item(
        ui.Button(
            style=discord.ButtonStyle.link,
            label="Go to giveaway",
            url=jump_url,
        )
    )
    return view


class EntriesPaginator(ui.View):
    """Ephemeral paginator for giveaway participants."""

    def __init__(
        self,
        pages: list[discord.Embed],
        *,
        owner_id: int,
        timeout: float = 120,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.owner_id = owner_id
        self.index = 0
        self._sync()

    def _sync(self) -> None:
        for child in self.children:
            if not isinstance(child, ui.Button):
                continue
            if child.custom_id == "gw:entries:prev":
                child.disabled = self.index <= 0
            elif child.custom_id == "gw:entries:next":
                child.disabled = self.index >= len(self.pages) - 1
            elif child.custom_id == "gw:entries:nav":
                child.label = f"{self.index + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "> -# only **you** can use this paginator", ephemeral=True
        )
        return False

    @ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="gw:entries:prev")
    async def prev(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self.index = max(0, self.index - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @ui.button(
        label="1/1",
        style=discord.ButtonStyle.secondary,
        custom_id="gw:entries:nav",
        disabled=True,
    )
    async def nav(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.defer()

    @ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="gw:entries:next")
    async def next(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)


def build_entries_pages(
    *,
    prize: str,
    members: list[discord.Member | discord.User | Any],
    per_page: int = 15,
) -> list[discord.Embed]:
    prize = (prize or "Giveaway").strip() or "Giveaway"
    if not members:
        emb = discord.Embed(
            title=f"Entries · {prize}",
            description="> -# **no entries** yet",
            color=color.base,
        )
        return [emb]

    lines = []
    for i, m in enumerate(members, 1):
        mention = getattr(m, "mention", None) or f"<@{getattr(m, 'id', m)}>"
        name = getattr(m, "display_name", None) or getattr(m, "name", "user")
        lines.append(f"`{i:02d}` {mention} · **{name}**")

    pages: list[discord.Embed] = []
    total = (len(lines) + per_page - 1) // per_page
    for page_i in range(total):
        chunk = lines[page_i * per_page : (page_i + 1) * per_page]
        emb = discord.Embed(
            title=f"Entries · {prize}",
            description="\n".join(chunk),
            color=color.base,
        )
        emb.set_footer(text=f"{len(members)} entr{'y' if len(members) == 1 else 'ies'} · page {page_i + 1}/{total}")
        pages.append(emb)
    return pages
