"""Monkey-patches discord.Interaction with styled response helpers.

Import this module once at bot startup to add .success(), .warning(), .fail()
methods to every discord.Interaction instance.

Usage in button callbacks:
    await interaction.warning(f"Only <@{user_id}> can use this!")
    await interaction.success("Done!")
    await interaction.fail("Invalid input.")
"""
from __future__ import annotations

import contextlib
from typing import Optional

import discord

from core.discord.views.embed import body

def _build_embed(
    interaction: discord.Interaction,
    message: str,
    *,
    emoji: str,
    color: int,
) -> discord.Embed:
    return discord.Embed(
        color=color,
        description=body(f"{emoji} {interaction.user.mention}: {message}"),
    )

async def _success(
    self: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
) -> None:
    from config import emojis, color as _color
    from core.managers.app_emojis import format_embed_emoji

    emoji = format_embed_emoji(self.client, emojis.approve, fallback_key="success")
    embed = _build_embed(self, message, emoji=emoji, color=_color.approve)
    send = (
        self.followup.send
        if self.response.is_done()
        else self.response.send_message
    )
    with contextlib.suppress(discord.HTTPException):
        await send(embed=embed, ephemeral=ephemeral)

async def _warning(
    self: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
) -> None:
    from config import emojis, color as _color
    from core.managers.app_emojis import format_embed_emoji

    emoji = format_embed_emoji(self.client, emojis.warn, fallback_key="warn")
    embed = _build_embed(self, message, emoji=emoji, color=_color.warn)
    send = (
        self.followup.send
        if self.response.is_done()
        else self.response.send_message
    )
    with contextlib.suppress(discord.HTTPException):
        await send(embed=embed, ephemeral=ephemeral)

async def _fail(
    self: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
) -> None:
    from config import emojis, color as _color
    from core.managers.app_emojis import format_embed_emoji

    emoji = format_embed_emoji(self.client, emojis.deny, fallback_key="deny")
    embed = _build_embed(self, message, emoji=emoji, color=_color.deny)
    send = (
        self.followup.send
        if self.response.is_done()
        else self.response.send_message
    )
    with contextlib.suppress(discord.HTTPException):
        await send(embed=embed, ephemeral=ephemeral)

async def _info(
    self: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
) -> None:
    from config import emojis, color as _color
    from core.managers.app_emojis import format_embed_emoji

    emoji = format_embed_emoji(self.client, emojis.interface.information, fallback_key="info")
    embed = _build_embed(self, message, emoji=emoji, color=_color.base)
    send = (
        self.followup.send
        if self.response.is_done()
        else self.response.send_message
    )
    with contextlib.suppress(discord.HTTPException):
        await send(embed=embed, ephemeral=ephemeral)

def patch_interaction() -> None:
    """call once at startup to add styled response methods to Interaction"""
    if not hasattr(discord.Interaction, "success"):
        discord.Interaction.success = _success
    if not hasattr(discord.Interaction, "warning"):
        discord.Interaction.warning = _warning
    if not hasattr(discord.Interaction, "fail"):
        discord.Interaction.fail = _fail
    if not hasattr(discord.Interaction, "deny"):
        discord.Interaction.deny = _fail
    if not hasattr(discord.Interaction, "info"):
        discord.Interaction.info = _info
