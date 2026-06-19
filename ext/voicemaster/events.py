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
    from .voicemaster import Voicemaster


class VoicemasterEvents(Cog):
    def __init__(self: "VoicemasterEvents", bot: discord.Client):
        self.bot = bot
        self.locks = defaultdict(Lock)
        self.voice_channels = {}

    async def create_voice_channel(self, member: discord.Member, category: discord.CategoryChannel) -> discord.VoiceChannel:
        channel_name = f"{member.display_name}'s Channel"
        
        overwrites = {
            member.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
            member: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True),
            member.guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True),
        }
        
        channel = await category.create_voice_channel(
            name=channel_name,
            overwrites=overwrites,
            reason=f"Voice channel created for {member.display_name}"
        )
        
        await self.bot.db.execute(
            "INSERT INTO voice_master_channels (guild_id, owner_id, channel_id, created_at) VALUES ($1, $2, $3, $4)",
            member.guild.id, member.id, channel.id, datetime.now()
        )
        
        self.voice_channels[channel.id] = member.id
        return channel

    async def delete_voice_channel(self, channel: discord.VoiceChannel):
        await self.bot.db.execute(
            "DELETE FROM voice_master_channels WHERE channel_id = $1",
            channel.id
        )
        self.voice_channels.pop(channel.id, None)
        await channel.delete(reason="Voice channel owner left")

    @Cog.listener("on_voice_state_update")
    async def on_voice_join(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not after.channel:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM voice_master_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('enabled', False):
            return
        
        if after.channel.id == config.get('join_channel'):
            category = member.guild.get_channel(config.get('category_id'))
            if not category or not isinstance(category, discord.CategoryChannel):
                return
            
            async with self.locks[f"voice_create:{member.id}"]:
                new_channel = await self.create_voice_channel(member, category)
                await member.move_to(new_channel, reason="Voice master channel created")

    @Cog.listener("on_voice_state_update")
    async def on_voice_leave(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not before.channel:
            return
        
        if before.channel.id in self.voice_channels:
            owner_id = self.voice_channels[before.channel.id]
            
            if owner_id == member.id:
                await self.delete_voice_channel(before.channel)
            else:
                members = before.channel.members
                if not members:
                    await self.delete_voice_channel(before.channel)

    @Cog.listener("on_voice_state_update")
    async def on_voice_channel_rename(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not after.channel or after.channel.id not in self.voice_channels:
            return
        
        owner_id = self.voice_channels[after.channel.id]
        if owner_id != member.id:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM voice_master_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('allow_rename', False):
            return
        
        new_name = f"{member.display_name}'s Channel"
        if after.channel.name != new_name:
            await after.channel.edit(name=new_name, reason="Voice channel name updated")

    @Cog.listener("on_voice_state_update")
    async def on_voice_channel_limit(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not after.channel or after.channel.id not in self.voice_channels:
            return
        
        owner_id = self.voice_channels[after.channel.id]
        if owner_id != member.id:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM voice_master_config WHERE guild_id = $1""", member.guild.id
        )
        if not config or not config.get('allow_limit', False):
            return
        
        member_count = len(after.channel.members)
        if after.channel.user_limit != member_count + 1:
            await after.channel.edit(user_limit=member_count + 1, reason="Voice channel limit updated")


async def setup(bot: discord.Client):
    await bot.add_cog(VoicemasterEvents(bot))
