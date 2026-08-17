from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package

if TYPE_CHECKING:
    from .. import Autorole
    from core.vain import Vain


class AutoroleEvents(Package):
    """Autorole event handlers (mixed into Server via ServerEvents)."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self.locks = defaultdict(asyncio.Lock)

    def _join_locks(self):
        """Prefer Server.join_locks when mixed in; else local locks."""
        locks = getattr(self, "join_locks", None)
        if locks is None:
            locks = getattr(self, "locks", None)
        if locks is None:
            self.locks = defaultdict(asyncio.Lock)
            locks = self.locks
        return locks

    @Package.listener("on_member_join")
    async def on_autorole(self, member: discord.Member) -> None:
        """Handle automatic role assignment on member join."""
        if await self.bot.object_cache.ratelimited(f"member_joins:{member.guild.id}", 1, 5) != 0:
            await asyncio.sleep(5)

        if member.bot:
            return

        async with self._join_locks()[f"member_joins:{member.guild.id}"]:
            roles = await self.bot.db.fetch(
                "SELECT role_id FROM auto_role WHERE guild_id = $1",
                member.guild.id,
            )
            if not roles:
                return

            to_delete = []
            roles_to_add = []
            for r in roles:
                role_id = r.role_id if hasattr(r, "role_id") else r["role_id"]
                role = member.guild.get_role(role_id)
                if not role:
                    to_delete.append(role_id)
                    continue
                # Skip managed / integration roles and roles the bot cannot assign
                if role.managed or role.is_default():
                    continue
                if role >= member.guild.me.top_role:
                    continue
                if role in member.roles:
                    continue
                roles_to_add.append(role)

            if roles_to_add:
                try:
                    await member.add_roles(*roles_to_add, reason="Auto Role")
                except (discord.Forbidden, discord.HTTPException):
                    pass

            if to_delete:
                await self.bot.db.execute(
                    "DELETE FROM auto_role WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])",
                    member.guild.id,
                    to_delete,
                )

    @Package.listener("on_raw_reaction_add")
    async def on_reaction_role_assign(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle reaction role assignment."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM reaction_role WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3 AND emoji = $4",
            guild.id,
            payload.channel_id,
            payload.message_id,
            str(payload.emoji),
        )
        if not role_id:
            return

        role = guild.get_role(role_id)
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        if member.bot:
            return

        if await self.bot.object_cache.ratelimited(f"reaction_roles:{member.guild.id}", 1, 5) != 0:
            await asyncio.sleep(5)

        async with self._join_locks()[f"reaction_roles:{member.guild.id}"]:
            await member.add_roles(role, reason="Reaction Role")

    @Package.listener("on_raw_reaction_remove")
    async def on_reaction_role_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle reaction role removal."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM reaction_role WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3 AND emoji = $4",
            guild.id,
            payload.channel_id,
            payload.message_id,
            str(payload.emoji),
        )
        if not role_id:
            return

        role = guild.get_role(role_id)
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        if member.bot:
            return

        if await self.bot.object_cache.ratelimited(f"reaction_roles:{member.guild.id}", 1, 5) != 0:
            await asyncio.sleep(5)

        async with self._join_locks()[f"reaction_roles:{member.guild.id}"]:
            await member.remove_roles(role, reason="Reaction Role")
