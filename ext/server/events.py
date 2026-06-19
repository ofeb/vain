from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import Embed, utils
from discord.ext import commands
from discord.ext.commands import Cog
from asyncio import Lock

if TYPE_CHECKING:
    from .server import Server


class Events(Cog):
    def __init__(self: "Events", bot: discord.Client):
        self.bot = bot
        self.locks = defaultdict(Lock)
        self.join_cache = {}

    @Cog.listener("on_member_join")
    async def on_server_boost(self, member: discord.Member):
        if member.premium_since:
            config = await self.bot.db.fetchrow(
                """SELECT * FROM server_config WHERE guild_id = $1""", member.guild.id
            )
            if not config or not config.get('boost_notifications', False):
                return
            
            boost_channel = member.guild.get_channel(config.get('boost_channel'))
            if not boost_channel:
                return
            
            embed = Embed(
                title="Server Boosted!",
                description=f"{member.mention} just boosted the server!",
                color=0xFF69B4
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Boosting Since", value=member.premium_since.strftime("%Y-%m-%d"), inline=True)
            
            await boost_channel.send(embed=embed)

    @Cog.listener("on_member_join")
    async def on_join_stats(self, member: discord.Member):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM server_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('join_stats', False):
            return
        
        self.join_cache[member.guild.id] = self.join_cache.get(member.guild.id, 0) + 1
        
        total_joins = self.join_cache[member.guild.id]
        member_count = len(member.guild.members)
        
        stats_channel = member.guild.get_channel(config.get('stats_channel'))
        if stats_channel:
            embed = Embed(
                title="Server Statistics",
                color=0x00FF00
            )
            embed.add_field(name="Total Members", value=str(member_count), inline=True)
            embed.add_field(name="Joins Today", value=str(total_joins), inline=True)
            embed.add_field(name="New Member", value=member.mention, inline=True)
            
            await stats_channel.send(embed=embed)

    @Cog.listener("on_guild_update")
    async def on_server_update(self, before: discord.Guild, after: discord.Guild):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM server_config WHERE guild_id = $1""", after.id
        )
        if not config or not config.get('change_logging', False):
            return
        
        log_channel = after.get_channel(config.get('log_channel'))
        if not log_channel:
            return
        
        changes = []
        
        if before.name != after.name:
            changes.append(f"Name: {before.name} → {after.name}")
        
        if before.icon != after.icon:
            changes.append("Server icon changed")
        
        if before.banner != after.banner:
            changes.append("Server banner changed")
        
        if before.description != after.description:
            changes.append(f"Description: {before.description or 'None'} → {after.description or 'None'}")
        
        if changes:
            embed = Embed(
                title="Server Updated",
                description="\n".join(changes),
                color=0xFFFF00
            )
            await log_channel.send(embed=embed)

    @Cog.listener("on_voice_state_update")
    async def on_voice_activity(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM server_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('voice_logging', False):
            return
        
        log_channel = member.guild.get_channel(config.get('log_channel'))
        if not log_channel:
            return
        
        if before.channel != after.channel:
            if after.channel and not before.channel:
                embed = Embed(
                    title="Voice Join",
                    description=f"{member.mention} joined {after.channel.mention}",
                    color=0x00FF00
                )
                await log_channel.send(embed=embed)
            elif before.channel and not after.channel:
                embed = Embed(
                    title="Voice Leave",
                    description=f"{member.mention} left {before.channel.mention}",
                    color=0xFF0000
                )
                await log_channel.send(embed=embed)
            elif before.channel and after.channel:
                embed = Embed(
                    title="Voice Move",
                    description=f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}",
                    color=0xFFFF00
                )
                await log_channel.send(embed=embed)


async def setup(bot: discord.Client):
    await bot.add_cog(Events(bot))
