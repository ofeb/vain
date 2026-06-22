from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import Embed, utils
from asyncio import Lock

from core.discord.package import Package

if TYPE_CHECKING:
    from core.bleed import Bleed


class InformationEvents(Package):
    def __init__(self: "InformationEvents", bot: Bleed):
        super().__init__(bot)
        self.locks = defaultdict(Lock)
        self.joined_cache = {}

    @Package.listener("on_member_join")
    async def on_join_info(self, member: discord.Member):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM information_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('join_info_enabled', False):
            return
        
        self.joined_cache[member.id] = datetime.now()
        
        info_channel = member.guild.get_channel(config.get('info_channel'))
        if not info_channel:
            return
        
        account_age = (datetime.now() - member.created_at).days
        embed = Embed(
            title="Member Joined",
            description=f"{member.mention} joined the server",
            color=0x00FF00
        )
        embed.add_field(name="Account Age", value=f"{account_age} days", inline=True)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await info_channel.send(embed=embed)

    @Package.listener("on_member_remove")
    async def on_leave_info(self, member: discord.Member):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM information_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('leave_info_enabled', False):
            return
        
        info_channel = member.guild.get_channel(config.get('info_channel'))
        if not info_channel:
            return
        
        join_time = self.joined_cache.get(member.id)
        duration = "Unknown"
        if join_time:
            duration = str(datetime.now() - join_time).split('.')[0]
        
        embed = Embed(
            title="Member Left",
            description=f"{member.name} left the server",
            color=0xFF0000
        )
        embed.add_field(name="Duration in Server", value=duration, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await info_channel.send(embed=embed)
        self.joined_cache.pop(member.id, None)

    @Package.listener("on_message_edit")
    async def on_message_edit_info(self, before: discord.Message, after: discord.Message):
        if before.author.bot:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM information_config WHERE guild_id = $1""", after.guild.id
        )
        if not config or not config.get('edit_info_enabled', False):
            return
        
        if before.content == after.content:
            return
        
        info_channel = after.guild.get_channel(config.get('info_channel'))
        if not info_channel:
            return
        
        embed = Embed(
            title="Message Edited",
            description=f"Message by {before.author.mention} was edited",
            color=0xFFFF00
        )
        embed.add_field(name="Before", value=before.content[:1024] or "None", inline=False)
        embed.add_field(name="After", value=after.content[:1024] or "None", inline=False)
        embed.add_field(name="Channel", value=after.channel.mention, inline=True)
        embed.add_field(name="Jump URL", value=f"[Jump to message]({after.jump_url})", inline=True)
        
        await info_channel.send(embed=embed)

    @Package.listener("on_message_delete")
    async def on_message_delete_info(self, message: discord.Message):
        if message.author.bot:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM information_config WHERE guild_id = $1""", message.guild.id
        )
        if not config or not config.get('delete_info_enabled', False):
            return
        
        info_channel = message.guild.get_channel(config.get('info_channel'))
        if not info_channel:
            return
        
        embed = Embed(
            title="Message Deleted",
            description=f"Message by {message.author.mention} was deleted",
            color=0xFF0000
        )
        if message.content:
            embed.add_field(name="Content", value=message.content[:1024], inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        
        await info_channel.send(embed=embed)

