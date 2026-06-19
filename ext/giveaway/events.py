from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import Embed, utils
from discord.ext import commands
from discord.ext.commands import Cog
from asyncio import Lock
from random import sample

if TYPE_CHECKING:
    from .giveaway import Giveaway


class GiveawayEvents(Cog):
    def __init__(self: "GiveawayEvents", bot: discord.Client):
        self.bot = bot
        self.locks = defaultdict(Lock)

    async def check_requirements(self, member: discord.Member, requirements: dict) -> bool:
        if requirements.get('required_roles'):
            member_roles = {role.id for role in member.roles}
            required = set(requirements['required_roles'])
            if not member_roles & required:
                return False
        
        if requirements.get('min_level'):
            level = await self.bot.db.fetchval(
                "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
                member.id, member.guild.id
            )
            if level and level < requirements['min_level']:
                return False
        
        if requirements.get('max_level'):
            level = await self.bot.db.fetchval(
                "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
                member.id, member.guild.id
            )
            if level and level > requirements['max_level']:
                return False
        
        return True

    @Cog.listener("on_raw_reaction_add")
    async def on_giveaway_entry(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1", payload.message_id
        )
        if not giveaway:
            return
        
        if str(payload.emoji) != "🎉":
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        member = guild.get_member(payload.user_id)
        if not member:
            return
        
        if datetime.now() > giveaway['ends_at']:
            return
        
        requirements = {
            'required_roles': giveaway.get('required_roles'),
            'min_level': giveaway.get('min_level'),
            'max_level': giveaway.get('max_level'),
        }
        
        if not await self.check_requirements(member, requirements):
            return
        
        async with self.locks[f"giveaway:{payload.message_id}"]:
            entries = giveaway.get('entries', [])
            if member.id not in entries:
                entries.append(member.id)
                await self.bot.db.execute(
                    "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                    entries, payload.message_id
                )

    @Cog.listener("on_raw_reaction_remove")
    async def on_giveaway_leave(self, payload: discord.RawReactionActionEvent):
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1", payload.message_id
        )
        if not giveaway:
            return
        
        if str(payload.emoji) != "🎉":
            return
        
        async with self.locks[f"giveaway:{payload.message_id}"]:
            entries = giveaway.get('entries', [])
            if payload.user_id in entries:
                entries.remove(payload.user_id)
                await self.bot.db.execute(
                    "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                    entries, payload.message_id
                )

    async def end_giveaway(self, giveaway: dict):
        message_id = giveaway['message_id']
        guild = self.bot.get_guild(giveaway['guild_id'])
        if not guild:
            return
        
        channel = guild.get_channel(giveaway['channel_id'])
        if not channel:
            return
        
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return
        
        entries = giveaway.get('entries', [])
        if not entries:
            embed = Embed(
                title="Giveaway Ended",
                description=f"Prize: {giveaway['prize']}\nNo valid entries!",
                color=0xFF0000
            )
            await message.edit(embed=embed)
            return
        
        members = [guild.get_member(user_id) for user_id in entries if guild.get_member(user_id)]
        if not members:
            embed = Embed(
                title="Giveaway Ended",
                description=f"Prize: {giveaway['prize']}\nNo valid members!",
                color=0xFF0000
            )
            await message.edit(embed=embed)
            return
        
        winners_count = giveaway.get('winners', 1)
        winners = sample(members, min(winners_count, len(members)))
        winners_text = ", ".join(w.mention for w in winners)
        
        embed = Embed(
            title="Giveaway Ended",
            description=f"Prize: {giveaway['prize']}\nWinner(s): {winners_text}",
            color=0x00FF00
        )
        await message.edit(embed=embed)
        
        await self.bot.db.execute(
            "UPDATE giveaways SET ended = TRUE, win_message_id = $1 WHERE message_id = $2",
            message.id, message_id
        )


async def setup(bot: discord.Client):
    await bot.add_cog(GiveawayEvents(bot))
