from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Optional

import discord

from core.discord.package import Package

if TYPE_CHECKING:
    from core.vain import Vain


class RoleEvents:
    """Role cache events for member leave/join."""

    def __init__(self, bot: Optional["Vain"] = None, *args, **kwargs):
        if bot is not None and not hasattr(self, "bot"):
            self.bot = bot

    @Package.listener("on_member_remove")
    async def role_cache(self, member: discord.Member) -> None:
        if member.bot:
            return
        me = member.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return
        role_ids = [role.id for role in member.roles if role.is_assignable()]
        if not role_ids:
            return
        await self._cache_set_roles(self.role_cache_key(member), role_ids, ex=3600)

    @Package.listener("on_member_join")
    async def role_restore_cache(self, member: discord.Member) -> None:
        guild = member.guild
        if member.bot:
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return

        key = self.role_cache_key(member)
        role_ids = await self._cache_get_roles(key)
        if not role_ids:
            return

        enabled, ignored = await self._get_reassign(guild.id)
        if not enabled:
            return

        ignored_set = set(ignored)
        roles = [
            role
            for role_id in role_ids
            if (role := guild.get_role(role_id)) is not None
            and role.is_assignable()
            and role not in member.roles
            and role.id not in ignored_set
            and role < me.top_role
        ]
        if not roles:
            return

        await self._cache_delete(key)
        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await member.add_roles(*roles, reason="Reassigned from cache")


__all__: list[str] = ["RoleEvents"]
