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
    from .manipulation import Manipulation


class Events(Cog):
    def __init__(self: "Events", bot: discord.Client):
        self.bot = bot
        self.locks = defaultdict(Lock)

    @Cog.listener("on_message")
    async def on_message_manipulation(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM manipulation_config WHERE guild_id = $1""", message.guild.id
        )
        if not config:
            return
        
        if config.get('auto_delete', False):
            for pattern in config.get('delete_patterns', []):
                if pattern.lower() in message.content.lower():
                    await message.delete()
                    return
        
        if config.get('auto_reply', False):
            for trigger, response in config.get('auto_replies', {}).items():
                if trigger.lower() in message.content.lower():
                    await message.channel.send(response)
                    return

    @Cog.listener("on_member_join")
    async def on_join_manipulation(self, member: discord.Member):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM manipulation_config WHERE guild_id = $1""", member.guild.id
        )
        if not config:
            return
        
        if config.get('auto_role_on_join', False):
            role_id = config.get('join_role_id')
            if role_id:
                role = member.guild.get_role(role_id)
                if role:
                    await member.add_roles(role, reason="Auto role on join")

    @Cog.listener("on_raw_reaction_add")
    async def on_reaction_manipulation(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        
        reaction_config = await self.bot.db.fetchrow(
            """SELECT * FROM reaction_roles WHERE message_id = $1 AND emoji = $2""",
            payload.message_id, str(payload.emoji)
        )
        if not reaction_config:
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        member = guild.get_member(payload.user_id)
        if not member:
            return
        
        role = guild.get_role(reaction_config['role_id'])
        if not role:
            return
        
        async with self.locks[f"reaction_role:{payload.message_id}:{payload.user_id}"]:
            await member.add_roles(role, reason="Reaction role")

    @Cog.listener("on_raw_reaction_remove")
    async def on_reaction_remove_manipulation(self, payload: discord.RawReactionActionEvent):
        reaction_config = await self.bot.db.fetchrow(
            """SELECT * FROM reaction_roles WHERE message_id = $1 AND emoji = $2""",
            payload.message_id, str(payload.emoji)
        )
        if not reaction_config:
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        member = guild.get_member(payload.user_id)
        if not member:
            return
        
        role = guild.get_role(reaction_config['role_id'])
        if not role:
            return
        
        async with self.locks[f"reaction_role:{payload.message_id}:{payload.user_id}"]:
            await member.remove_roles(role, reason="Reaction role removed")


async def setup(bot: discord.Client):
    await bot.add_cog(Events(bot))
