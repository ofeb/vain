from __future__ import annotations

import discord
from discord import app_commands

from core.tools.guild_members import collect_guild_members, is_guild_member_cache_complete


def _resolve_guild(interaction: discord.Interaction) -> discord.Guild | None:
    if interaction.guild is not None:
        return interaction.guild
    if interaction.guild_id is None:
        return None
    return interaction.client.get_guild(interaction.guild_id)


def _user_label(user: discord.User | discord.Member) -> str:
    return user.display_name or user.name


def _channel_users(
    interaction: discord.Interaction,
) -> list[discord.User | discord.Member]:
    user = interaction.user
    guild = _resolve_guild(interaction)
    if guild is not None:
        return list(guild.members)

    channel = interaction.channel
    if isinstance(channel, discord.GroupChannel):
        return [
            recipient
            for recipient in channel.recipients
            if recipient.id != user.id and not recipient.bot
        ]

    if isinstance(channel, discord.DMChannel) and channel.recipient:
        if channel.recipient.bot or channel.recipient.id == user.id:
            return []
        return [channel.recipient]

    return []


async def _collect_candidates(
    interaction: discord.Interaction,
) -> list[discord.User | discord.Member]:
    guild = _resolve_guild(interaction)
    if guild is not None:
        if is_guild_member_cache_complete(guild):
            return list(guild.members)
        return await collect_guild_members(guild, timeout=8.0)
    return _channel_users(interaction)


async def guild_member_choices(
    interaction: discord.Interaction,
    current: str,
    *,
    include_me: bool = False,
) -> list[app_commands.Choice[str]]:
    needle = (current or "").lower()
    choices: list[app_commands.Choice[str]] = []

    if include_me and (
        not needle or any(x in needle for x in ("me", "refrain", "bot", "i"))
    ):
        choices.append(app_commands.Choice(name="Me", value="0"))

    candidates = await _collect_candidates(interaction)
    slots = 25 - len(choices)
    ranked: list[tuple[str, discord.User | discord.Member]] = []

    for candidate in candidates:
        if candidate.bot or candidate.id == interaction.user.id:
            continue
        label = _user_label(candidate)
        if needle and needle not in label.lower() and needle not in candidate.name.lower():
            continue
        ranked.append((label.lower(), candidate))

    ranked.sort(key=lambda item: item[0])
    for _, candidate in ranked[:slots]:
        label = _user_label(candidate)
        choices.append(app_commands.Choice(name=label[:100], value=str(candidate.id)))

    return choices
