from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from .counters import Counters


class CountersEvents(commands.Cog):
    """Counter event handlers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rl_helper = {}

    async def ratelimit(self, key: str, rate: int, per: int) -> bool:
        if key not in self.rl_helper:
            self.rl_helper[key] = []
        
        now = asyncio.get_event_loop().time()
        self.rl_helper[key] = [t for t in self.rl_helper[key] if now - t < per]
        
        if len(self.rl_helper[key]) >= rate:
            return True
        
        self.rl_helper[key].append(now)
        return False

    @commands.Cog.listener("on_member_join")
    async def on_member_counter_add(self, member: discord.Member) -> None:
        guild = member.guild
        counter = await self.bot.db.fetchrow(
            "SELECT * FROM counters WHERE guild_id = $1 AND counter_type = $2",
            guild.id,
            "members",
        )
        if not counter:
            return
        
        counter_channel = guild.get_channel(counter["channel_id"])
        if counter_channel:
            if await self.ratelimit(f"counter_edit:{guild.id}", 1, 10):
                await asyncio.sleep(10)
            await counter_channel.edit(name=f"{len(guild.members)} members")

    @commands.Cog.listener("on_member_remove")
    async def on_member_counter_remove(self, member: discord.Member) -> None:
        guild = member.guild
        counter = await self.bot.db.fetchrow(
            "SELECT * FROM counters WHERE guild_id = $1 AND counter_type = $2",
            guild.id,
            "members",
        )
        if not counter:
            return
        
        counter_channel = guild.get_channel(counter["channel_id"])
        if counter_channel:
            if await self.ratelimit(f"counter_edit:{guild.id}", 1, 10):
                await asyncio.sleep(10)
            await counter_channel.edit(name=f"{len(guild.members)} members")

    @commands.Cog.listener("on_member_update")
    async def on_booster_counter_change(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild
        booster_counter = await self.bot.db.fetchrow(
            "SELECT * FROM counters WHERE guild_id = $1 AND counter_type = $2",
            guild.id,
            "boosters",
        )
        boost_counter = await self.bot.db.fetchrow(
            "SELECT * FROM counters WHERE guild_id = $1 AND counter_type = $2",
            guild.id,
            "boosts",
        )
        
        if not boost_counter and not booster_counter:
            return
        
        boost_counter_channel = guild.get_channel(boost_counter["channel_id"]) if boost_counter else None
        booster_counter_channel = guild.get_channel(booster_counter["channel_id"]) if booster_counter else None
        
        if await self.ratelimit(f"counter_edit:{guild.id}", 1, 10):
            await asyncio.sleep(10)
        
        if boost_counter_channel:
            num = guild.premium_subscription_count
            await boost_counter_channel.edit(name=f"{num} boosts")
        
        if booster_counter_channel:
            num = len(guild.premium_subscribers)
            await booster_counter_channel.edit(name=f"{num} boosters")


async def setup(bot: commands.Bot):
    await bot.add_cog(CountersEvents(bot))
