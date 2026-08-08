from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

import discord
from discord import ui
from discord.ext import commands

from config import emojis
from core.tools.embed import Script, maybe_wrap_embed_script, to_code

if TYPE_CHECKING:
    from core.vain import Vain


def _custom_ids(message_id: int) -> dict[str, str]:
    base = f"Vain:pag:{message_id}"
    return {
        "prev": f"{base}:prev",
        "next": f"{base}:next",
        "goto": f"{base}:goto",
        "cancel": f"{base}:cancel",
    }


class _StoredSkipModal(ui.Modal, title="Skip to page"):
    def __init__(self, view: "StoredPaginationView", total: int) -> None:
        super().__init__(timeout=60)
        self.view = view
        self.page = ui.TextInput(
            label="Page number",
            placeholder=f"1-{total}",
            required=True,
            max_length=4,
        )
        self.add_item(self.page)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.page.value).strip()
        if not raw.isdigit():
            return await interaction.response.send_message(
                "Provide a **valid page number**.",
                ephemeral=True,
            )
        page_number = int(raw)
        if page_number < 1 or page_number > len(self.view.pages):
            return await interaction.response.send_message(
                "That page is **out of range**.",
                ephemeral=True,
            )
        await self.view.show_page(interaction, page_number - 1)


class _StoredButton(ui.Button["StoredPaginationView"]):
    def __init__(self, *, action: str, custom_id: str, **kwargs) -> None:
        super().__init__(custom_id=custom_id, **kwargs)
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            return
        if self.action == "cancel":
            await interaction.response.defer()
            if interaction.message is not None:
                with suppress(discord.HTTPException):
                    await interaction.message.delete()
            await view.bot.db.execute(
                """
                DELETE FROM pagination
                WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
                """,
                view.guild_id,
                view.channel_id,
                view.message_id,
            )
            view.stop()
            return
        if self.action == "goto":
            return await interaction.response.send_modal(
                _StoredSkipModal(view, len(view.pages))
            )
        if self.action == "prev":
            return await view.show_page(interaction, view.index - 1)
        if self.action == "next":
            return await view.show_page(interaction, view.index + 1)


class StoredPaginationView(ui.View):
    """persistent button pagination for ,ce / pagination set messages."""

    def __init__(
        self,
        bot: Vain,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        pages: list[str],
        current_page: int = 0,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.pages = pages
        self.index = min(max(current_page, 0), max(len(pages) - 1, 0))
        ids = _custom_ids(message_id)
        
        # Order: previous · delete · next · search
        self.add_item(
            _StoredButton(
                action="prev",
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
                custom_id=ids["prev"],
            )
        )
        self.add_item(
            _StoredButton(
                action="cancel",
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(
                    getattr(emojis.paginator, "delete", None)
                    or emojis.paginator.cancel
                    or "<:delete:1535040504516055191>"
                ),
                custom_id=ids["cancel"],
            )
        )
        self.add_item(
            _StoredButton(
                action="next",
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.next),
                custom_id=ids["next"],
            )
        )
        self.add_item(
            _StoredButton(
                action="goto",
                style=discord.ButtonStyle.primary,
                emoji=discord.PartialEmoji.from_str(
                    getattr(emojis.paginator, "search", None)
                    or emojis.paginator.navigate
                    or "<:search:1479154501066817600>"
                ),
                custom_id=ids["goto"],
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def _payload(self, index: int) -> dict:
        script = Script(self.pages[index], self.bot.user)
        return await script.data(True)

    async def show_page(self, interaction: discord.Interaction, index: int) -> None:
        if len(self.pages) <= 1:
            return
        self.index = index % len(self.pages)
        await self.bot.db.execute(
            """
            UPDATE pagination
            SET current_page = $1
            WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4
            """,
            self.index,
            self.guild_id,
            self.channel_id,
            self.message_id,
        )
        payload = await self._payload(self.index)
        payload["view"] = self
        await interaction.response.edit_message(**payload)


async def sync_stored_pagination(
    bot: Vain,
    *,
    guild_id: int,
    channel_id: int,
    message: discord.Message,
    pages: list[str],
    current_page: int = 0,
) -> None:
    """attach, refresh, or remove stored pagination buttons on a message."""
    index = min(max(current_page, 0), max(len(pages) - 1, 0))
    if len(pages) <= 1:
        if pages:
            script = Script(pages[index], bot.user)
            payload = await script.data(True)
            payload["view"] = None
            await message.edit(**payload)
        else:
            await message.edit(view=None)
        return
    view = StoredPaginationView(
        bot,
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message.id,
        pages=pages,
        current_page=index,
    )
    bot.add_view(view)
    script = Script(pages[index], bot.user)
    payload = await script.data(True)
    payload["view"] = view
    await message.edit(**payload)


async def show_stored_page_by_reaction(
    bot: Vain,
    *,
    guild_id: int,
    channel_id: int,
    message: discord.Message,
    direction: int,
) -> None:
    """Flip a stored pagination page via left/right reactions. direction: -1 or +1."""
    row = await bot.db.fetchrow(
        """
        SELECT pages, current_page
        FROM pagination
        WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
        """,
        guild_id,
        channel_id,
        message.id,
    )
    if not row:
        return
    pages = list(row["pages"] or [])
    if len(pages) <= 1:
        return
    index = (int(row["current_page"] or 0) + direction) % len(pages)
    await bot.db.execute(
        """
        UPDATE pagination
        SET current_page = $1
        WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4
        """,
        index,
        guild_id,
        channel_id,
        message.id,
    )
    view = StoredPaginationView(
        bot,
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message.id,
        pages=pages,
        current_page=index,
    )
    bot.add_view(view)
    script = Script(pages[index], bot.user)
    payload = await script.data(True)
    payload["view"] = view
    with suppress(discord.HTTPException):
        await message.edit(**payload)


async def register_stored_paginations(bot: Vain) -> None:
    """restore persistent pagination views after startup."""
    rows = await bot.db.fetch(
        """
        SELECT guild_id, channel_id, message_id, pages, current_page
        FROM pagination
        WHERE COALESCE(array_length(pages, 1), 0) > 1
        """,
        cached=False,
    )
    for row in rows:
        pages = list(row["pages"] or [])
        if len(pages) <= 1:
            continue
        view = StoredPaginationView(
            bot,
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]),
            pages=pages,
            current_page=int(row["current_page"] or 0),
        )
        bot.add_view(view)


class PaginationReactionListener(commands.Cog):
    """left/right reaction flips for stored pagination messages."""

    def __init__(self, bot: Vain) -> None:
        self.bot = bot

    def _match_side(self, emoji: discord.PartialEmoji | discord.Emoji | str, left: str, right: str) -> int | None:
        raw = str(emoji)
        left_s = str(left or emojis.paginator.left)
        right_s = str(right or emojis.paginator.right)
        
        left_aliases = {left_s, "⬅️", "⬅", "◀️", "◀"}
        right_aliases = {right_s, "➡️", "➡", "▶️", "▶"}
        if raw in left_aliases or getattr(emoji, "name", None) in {
            "arrow_left",
            "leftwards_arrow_with_hook",
        }:
            return -1
        if raw in right_aliases or getattr(emoji, "name", None) in {"arrow_right"}:
            return 1
        
        eid = getattr(emoji, "id", None)
        if eid:
            if str(eid) in left_s:
                return -1
            if str(eid) in right_s:
                return 1
        return None

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_pagination_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or not payload.message_id:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        row = await self.bot.db.fetchrow(
            """
            SELECT pages, current_page, left_emoji, right_emoji
            FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            payload.guild_id,
            payload.channel_id,
            payload.message_id,
        )
        if not row:
            
            row = await self.bot.db.fetchrow(
                """
                SELECT pages, current_page
                FROM pagination
                WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
                """,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
            )
        if not row:
            return
        pages = list(row["pages"] or [])
        if len(pages) <= 1:
            return

        left = emojis.paginator.left
        right = emojis.paginator.right
        with suppress(Exception):
            left = row["left_emoji"] or left
        with suppress(Exception):
            right = row["right_emoji"] or right

        direction = self._match_side(payload.emoji, left, right)
        if direction is None:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            with suppress(Exception):
                channel = await self.bot.fetch_channel(payload.channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        
        with suppress(discord.HTTPException):
            await message.remove_reaction(payload.emoji, discord.Object(id=payload.user_id))

        await show_stored_page_by_reaction(
            self.bot,
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message=message,
            direction=direction,
        )


def embed_script_from_message(message: discord.Message) -> str:
    if message.embeds:
        return to_code(message.embeds[0], message.content)

    content = message.content or ""
    if not content.strip() and not message.components:
        raise ValueError("message has no content or embed")

    if content.strip():
        wrapped = maybe_wrap_embed_script(content)
        if wrapped.startswith("{") and not wrapped.lower().startswith("{embed}"):
            code = f"{{embed}}$v{wrapped}"
        else:
            code = wrapped
    else:
        code = "{embed}"

    for component in message.components:
        children = (
            [component]
            if isinstance(component, discord.Button)
            else getattr(component, "children", [])
        )
        for button in children:
            if isinstance(button, discord.Button) and button.url:
                code += f"$v{{button: {button.label or ''} && {button.url}}}"
    return code
