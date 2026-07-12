from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import discord
from asyncio import Lock

from core.discord.package import Package


class ModerationEvents(Package):
    def __init__(self, bot):
        super().__init__(bot)
        self.locks = defaultdict(Lock)
        self.mute_cache = {}

    async def check_mute_expiry(self, member: discord.Member) -> bool:
        mute_data = await self.bot.db.fetchrow(
            "SELECT * FROM mutes WHERE user_id = $1 AND guild_id = $2",
            member.id, member.guild.id
        )
        if not mute_data:
            return False
        
        if mute_data['expires_at'] and datetime.now() > mute_data['expires_at']:
            await self.bot.db.execute(
                "DELETE FROM mutes WHERE user_id = $1 AND guild_id = $2",
                member.id, member.guild.id
            )
            mute_role = member.guild.get_role(mute_data['role_id'])
            if mute_role and mute_role in member.roles:
                await member.remove_roles(mute_role, reason="Mute expired")
            return True
        
        return False

    @Package.listener("on_member_join")
    async def on_mute_restore(self, member: discord.Member):
        mute_data = await self.bot.db.fetchrow(
            "SELECT * FROM mutes WHERE user_id = $1 AND guild_id = $2",
            member.id, member.guild.id
        )
        if not mute_data:
            return
        
        if mute_data['expires_at'] and datetime.now() > mute_data['expires_at']:
            await self.bot.db.execute(
                "DELETE FROM mutes WHERE user_id = $1 AND guild_id = $2",
                member.id, member.guild.id
            )
            return
        
        mute_role = member.guild.get_role(mute_data['role_id'])
        if mute_role:
            await member.add_roles(mute_role, reason="Mute restored on rejoin")

    @Package.listener("on_message")
    async def on_mute_check(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        if await self.check_mute_expiry(message.author):
            return
        
        mute_data = await self.bot.db.fetchrow(
            "SELECT * FROM mutes WHERE user_id = $1 AND guild_id = $2",
            message.author.id, message.guild.id
        )
        if mute_data:
            mute_role = message.guild.get_role(mute_data['role_id'])
            if mute_role and mute_role in message.author.roles:
                await message.delete()
                try:
                    await message.author.send(f"You are muted in {message.guild.name}")
                except discord.Forbidden:
                    pass

    @Package.listener("on_member_update")
    async def on_role_change_log(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        
        config = await self.bot.db.fetchrow(
            """SELECT * FROM moderation_config WHERE guild_id = $1""", after.guild.id
        )
        if not config or not config.get('role_change_logging', False):
            return
        
        log_channel = after.guild.get_channel(config.get('log_channel'))
        if not log_channel:
            return
        
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)
        
        embed = discord.Embed(
            title="Role Changes",
            description=f"Roles updated for {after.mention}",
            color=0xD4B8D0
        )
        
        if added_roles:
            embed.add_field(
                name="Added Roles",
                value=", ".join(role.mention for role in added_roles),
                inline=False
            )
        
        if removed_roles:
            embed.add_field(
                name="Removed Roles",
                value=", ".join(role.mention for role in removed_roles),
                inline=False
            )
        
        await log_channel.send(embed=embed)

    @Package.listener("on_member_ban")
    async def on_ban_log(self, guild: discord.Guild, user: discord.User):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM moderation_config WHERE guild_id = $1""", guild.id
        )
        if not config or not config.get('ban_logging', False):
            return
        
        log_channel = guild.get_channel(config.get('log_channel'))
        if not log_channel:
            return
        
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                embed = discord.Embed(
                    title="Member Banned",
                    description=f"{user.name} was banned by {entry.user.mention}",
                    color=0xE07A7A
                )
                if entry.reason:
                    embed.add_field(name="Reason", value=entry.reason, inline=False)
                await log_channel.send(embed=embed)
                break

    @Package.listener("on_member_unban")
    async def on_unban_log(self, guild: discord.Guild, user: discord.User):
        config = await self.bot.db.fetchrow(
            """SELECT * FROM moderation_config WHERE guild_id = $1""", guild.id
        )
        if not config or not config.get('ban_logging', False):
            return
        
        log_channel = guild.get_channel(config.get('log_channel'))
        if not log_channel:
            return
        
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
            if entry.target.id == user.id:
                embed = discord.Embed(
                    title="Member Unbanned",
                    description=f"{user.name} was unbanned by {entry.user.mention}",
                    color=0xA8D8A8
                )
                await log_channel.send(embed=embed)
                break

