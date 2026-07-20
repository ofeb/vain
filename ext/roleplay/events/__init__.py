from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import Embed, utils
from discord.ext import commands
from asyncio import Lock
import random

from core.discord.package import Package

if TYPE_CHECKING:
    from core.vain import Vain
    from ..roleplay import Roleplay


class RoleplayEvents(Package):
    def __init__(self: "RoleplayEvents", bot: Vain):
        super().__init__(bot)
        self.locks = defaultdict(Lock)
        self.character_cache = {}

    @Package.listener("on_message")
    async def on_roleplay_action(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM roleplay_config WHERE guild_id = $1""", message.guild.id
        )
        if not config or not config.get('enabled', False):
            return
        
        if message.content.startswith(config.get('action_prefix', '*')):
            action = message.content[len(config.get('action_prefix', '*')):]
            if config.get('action_channel'):
                action_channel = message.guild.get_channel(config.get('action_channel'))
                if action_channel and message.channel.id != action_channel.id:
                    return
            
            embed = Embed(
                description=f"**{message.author.display_name}** {action}",
                color=message.author.color
            )
            embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
            
            if config.get('delete_original', False):
                await message.delete()
            
            await message.channel.send(embed=embed)

    @Package.listener("on_message")
    async def on_character_tracking(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM roleplay_config WHERE guild_id = $1""", message.guild.id
        )
        if not config or not config.get('character_tracking', False):
            return
        
        character_data = await self.bot.db.fetchrow(
            "SELECT * FROM characters WHERE user_id = $1 AND guild_id = $2",
            message.author.id, message.guild.id
        )
        
        if character_data:
            await self.bot.db.execute(
                "UPDATE characters SET message_count = message_count + 1 WHERE user_id = $1 AND guild_id = $2",
                message.author.id, message.guild.id
            )

    @Package.listener("on_raw_reaction_add")
    async def on_character_reaction(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM roleplay_config WHERE guild_id = $1""", payload.guild_id
        )
        if not config or not config.get('character_cards', False):
            return
        
        if str(payload.emoji) != config.get('card_emoji', '🎭'):
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        member = guild.get_member(payload.user_id)
        if not member:
            return
        
        character_data = await self.bot.db.fetchrow(
            "SELECT * FROM characters WHERE user_id = $1 AND guild_id = $2",
            payload.user_id, payload.guild_id
        )
        
        if not character_data:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        message = await channel.fetch_message(payload.message_id)
        
        embed = Embed(
            title=f"Character Card: {character_data['name']}",
            description=character_data['description'] or "No description",
            color=member.color
        )
        embed.add_field(name="Played by", value=member.mention, inline=True)
        embed.add_field(name="Messages", value=str(character_data.get('message_count', 0)), inline=True)
        if character_data.get('avatar_url'):
            embed.set_thumbnail(url=character_data['avatar_url'])
        
        await message.reply(embed=embed)


async def setup(bot: Vain):
    await bot.add_cog(RoleplayEvents(bot))
