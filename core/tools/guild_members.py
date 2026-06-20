from __future__ import annotations

import asyncio

import discord


def is_guild_member_cache_complete(guild: discord.Guild) -> bool:
    total = guild.member_count
    if total is None:
        return bool(guild.members)
    return len(guild.members) >= total


async def collect_guild_members(
    guild: discord.Guild,
    *,
    timeout: float = 30.0,
    cache: bool = False,
) -> list[discord.Member]:
    if is_guild_member_cache_complete(guild):
        return list(guild.members)

    members: list[discord.Member] = []
    try:
        members = await asyncio.wait_for(guild.chunk(cache=cache), timeout=timeout)
    except (asyncio.TimeoutError, discord.ClientException, discord.HTTPException):
        members = []
    if members:
        return members

    try:
        async for member in guild.fetch_members(limit=None):
            members.append(member)
    except discord.HTTPException:
        return list(guild.members)

    return members or list(guild.members)
