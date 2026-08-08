from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord import Embed, utils
from asyncio import Lock

from core.discord.package import Package

if TYPE_CHECKING:
    from core.vain import Vain


class InformationEvents(Package):
    def __init__(self: "InformationEvents", bot: Vain):
        super().__init__(bot)
        self.locks = defaultdict(Lock)
        self.joined_cache = {}
        
        if not hasattr(bot, "member_last_seen"):
            bot.member_last_seen = {}
        
        if not hasattr(bot, "member_last_online"):
            bot.member_last_online = {}

    @Package.listener("on_message")
    async def on_member_seen(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        now = message.created_at
        key = (message.guild.id, message.author.id)
        self.bot.member_last_seen[key] = now
        
        self.bot.member_last_online[key] = now
        
        if len(self.bot.member_last_seen) > 20_000:
            
            self.bot.member_last_seen.clear()
        if len(self.bot.member_last_online) > 20_000:
            self.bot.member_last_online.clear()

    @Package.listener("on_presence_update")
    async def on_member_presence_seen(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Track last time a member was online (status left offline)."""
        if after.bot or after.guild is None:
            return
        
        if after.status is not discord.Status.offline:
            self.bot.member_last_online[(after.guild.id, after.id)] = discord.utils.utcnow()
        
        elif before.status is not discord.Status.offline and after.status is discord.Status.offline:
            key = (after.guild.id, after.id)
            self.bot.member_last_online[key] = discord.utils.utcnow()

    async def _fetch_config(self, guild_id: int):
        try:
            return await self.bot.db.fetchrow(
                """SELECT * FROM information_config WHERE guild_id = $1""",
                guild_id,
            )
        except asyncpg.UndefinedTableError:
            return None

    @Package.listener("on_member_join")
    async def on_join_info(self, member: discord.Member):
        config = await self._fetch_config(member.guild.id)
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
            color=0xE1D2DE
        )
        embed.add_field(name="Account Age", value=f"{account_age} days", inline=True)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await info_channel.send(embed=embed)

    @Package.listener("on_member_remove")
    async def on_leave_info(self, member: discord.Member):
        config = await self._fetch_config(member.guild.id)
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
            color=0xE07A7A
        )
        embed.add_field(name="Duration in Server", value=duration, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await info_channel.send(embed=embed)
        self.joined_cache.pop(member.id, None)

    @Package.listener("on_message_edit")
    async def on_message_edit_info(self, before: discord.Message, after: discord.Message):
        if before.author.bot:
            return
        
        config = await self._fetch_config(after.guild.id)
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
            color=0xC9B3C4
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
        
        config = await self._fetch_config(message.guild.id)
        if not config or not config.get('delete_info_enabled', False):
            return
        
        info_channel = message.guild.get_channel(config.get('info_channel'))
        if not info_channel:
            return
        
        embed = Embed(
            title="Message Deleted",
            description=f"Message by {message.author.mention} was deleted",
            color=0xD4C0D0
        )
        if message.content:
            embed.add_field(name="Content", value=message.content[:1024], inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        
        await info_channel.send(embed=embed)

