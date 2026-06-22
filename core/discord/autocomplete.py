from __future__ import annotations

import discord
from discord import app_commands


async def guild_member_choices(
    interaction: discord.Interaction,
    current: str,
    *,
    include_ai: bool = False,
) -> list[app_commands.Choice[str]]:
    guild = interaction.guild
    if guild is None:
        return []

    needle = (current or "").lower()
    choices: list[app_commands.Choice[str]] = []

    if include_ai and (not needle or "ai" in needle):
        choices.append(app_commands.Choice(name="AI opponent", value="0"))

    for member in guild.members:
        if member.bot or member.id == interaction.user.id:
            continue
        label = member.display_name
        if needle and needle not in label.lower() and needle not in member.name.lower():
            continue
        choices.append(app_commands.Choice(name=label[:100], value=str(member.id)))
        if len(choices) >= 25:
            break

    return choices
