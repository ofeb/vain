from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from config import emojis
from core.tools.embed import Script, maybe_wrap_embed_script, to_code

if TYPE_CHECKING:
    from core.vain import Vain


async def _stored_reaction_emojis(
    bot: Vain,
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
) -> tuple[str, str]:
    row = await bot.db.fetchrow(
        """
        SELECT left_emoji, right_emoji
        FROM pagination
        WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
        """,
        guild_id,
        channel_id,
        message_id,
    )
    left = emojis.paginator.left
    right = emojis.paginator.right
    if row:
        with suppress(Exception):
            left = row["left_emoji"] or left
        with suppress(Exception):
            right = row["right_emoji"] or right
    return left, right


async def _apply_pagination_reactions(
    message: discord.Message,
    *,
    left: str | None = None,
    right: str | None = None,
) -> tuple[str, str]:
    """Ensure left/right reaction controls exist on a pagination message."""
    left_emoji = left or getattr(emojis.paginator, "left", "⬅️") or "⬅️"
    right_emoji = right or getattr(emojis.paginator, "right", "➡️") or "➡️"

    with suppress(discord.HTTPException):
        await message.clear_reactions()

    with suppress(discord.HTTPException):
        await message.add_reaction(left_emoji)
    with suppress(discord.HTTPException):
        await message.add_reaction(right_emoji)
    return left_emoji, right_emoji


async def sync_stored_pagination(
    bot: Vain,
    *,
    guild_id: int,
    channel_id: int,
    message: discord.Message,
    pages: list[str],
    current_page: int = 0,
) -> None:
    """Render a stored pagination and keep its left/right reaction controls."""
    index = min(max(current_page, 0), max(len(pages) - 1, 0))
    if len(pages) <= 1:
        if pages:
            script = Script(pages[index], bot.user)
            payload = await script.data(True)
            payload["view"] = None
            with suppress(discord.HTTPException):
                await message.edit(**payload)
        else:
            with suppress(discord.HTTPException):
                await message.edit(view=None)
        with suppress(discord.HTTPException):
            await message.clear_reactions()
        return

    left, right = await _stored_reaction_emojis(
        bot,
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message.id,
    )
    script = Script(pages[index], bot.user)
    payload = await script.data(True)
    payload["view"] = None
    with suppress(discord.HTTPException):
        await message.edit(**payload)
    await _apply_pagination_reactions(message, left=left, right=right)


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
    script = Script(pages[index], bot.user)
    payload = await script.data(True)
    payload["view"] = None
    with suppress(discord.HTTPException):
        await message.edit(**payload)


async def register_stored_paginations(bot: Vain) -> None:
    """restore stored pagination messages without buttons and with reactions."""
    rows = await bot.db.fetch(
        """
        SELECT guild_id, channel_id, message_id, pages, current_page
        FROM pagination
        WHERE COALESCE(array_length(pages, 1), 0) > 1
        """,
        cached=False,
    )
    for row in rows:
        channel = bot.get_channel(int(row["channel_id"]))
        if channel is None:
            with suppress(Exception):
                channel = await bot.fetch_channel(int(row["channel_id"]))
        if channel is None or not hasattr(channel, "fetch_message"):
            continue
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except Exception:
            continue
        pages = list(row["pages"] or [])
        if not pages:
            continue
        index = min(max(int(row["current_page"] or 0), 0), len(pages) - 1)
        script = Script(pages[index], bot.user)
        payload = await script.data(True)
        payload["view"] = None
        with suppress(discord.HTTPException):
            await message.edit(**payload)
        left, right = await _stored_reaction_emojis(
            bot,
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            message_id=int(row["message_id"]),
        )
        await _apply_pagination_reactions(message, left=left, right=right)


class PaginationReactionListener(commands.Cog):
    """left/right reaction flips for stored pagination messages (Manage Server only)."""

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

        member = payload.member
        if member is None:
            guild = self.bot.get_guild(payload.guild_id)
            if guild is not None:
                with suppress(Exception):
                    member = guild.get_member(payload.user_id)
                if member is None:
                    with suppress(Exception):
                        member = await guild.fetch_member(payload.user_id)
        if member is None or not member.guild_permissions.manage_guild:
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
            await message.remove_reaction(
                payload.emoji, discord.Object(id=payload.user_id)
            )

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
