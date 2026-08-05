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
    """Autorole event handlers."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self.locks = defaultdict(asyncio.Lock)

    @Package.listener("on_member_join")
    async def on_autorole(self, member: discord.Member) -> None:
        """Handle automatic role assignment on member join."""
        if await self.bot.object_cache.ratelimited(f"member_joins:{member.guild.id}", 1, 5) != 0:
            await asyncio.sleep(5)
        
        if member.bot:
            return
        
        async with self.locks[f"member_joins:{member.guild.id}"]:
            roles = await self.bot.db.fetch(
                "SELECT role_id FROM auto_role WHERE guild_id = $1",
                member.guild.id,
            )
            if not roles:
                return
            
            to_delete = []
            role_ids = [r.role_id for r in roles]
            valid_roles = member.roles
            for role_id in role_ids:
                role = member.guild.get_role(role_id)
                if not role:
                    to_delete.append(role_id)
                    continue
                if role.is_dangerous:
                    continue
                valid_roles.append(role)
            
            await member.edit(roles=valid_roles, reason="Auto Role")
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
        
        async with self.locks[f"reaction_roles:{member.guild.id}"]:
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
        
        async with self.locks[f"reaction_roles:{member.guild.id}"]:
            await member.remove_roles(role, reason="Reaction Role")


async def setup(bot: Vain):
    """Load the AutoroleEvents cog."""
    await bot.add_cog(AutoroleEvents(bot))
