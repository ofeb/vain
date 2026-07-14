from __future__ import annotations

import contextlib
from collections import defaultdict
from datetime import datetime

import discord
from asyncio import Lock

from core.discord.package import Package
from core.tools.aesthetic import label_line, panel_embed


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
    async def on_hardban_reban(self, member: discord.Member) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        if not await self.db.is_hardbanned(member.guild.id, member.id):
            return
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await member.guild.ban(
                member,
                delete_message_seconds=0,
                reason="hardban - member rejoined",
            )

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
        
        lines = [f"Roles updated for {after.mention}"]
        if added_roles:
            lines.append(label_line("Added Roles", ", ".join(role.mention for role in added_roles)))
        if removed_roles:
            lines.append(label_line("Removed Roles", ", ".join(role.mention for role in removed_roles)))

        embed = panel_embed(
            title="Role Changes",
            color=0xD4B8D0,
            lines=lines,
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
                lines = [f"{user.name} was banned by {entry.user.mention}"]
                if entry.reason:
                    lines.append(label_line("Reason", entry.reason))
                embed = panel_embed(
                    title="Member Banned",
                    color=0xE07A7A,
                    lines=lines,
                )
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
                embed = panel_embed(
                    title="Member Unbanned",
                    color=0xA8D8A8,
                    lines=[f"{user.name} was unbanned by {entry.user.mention}"],
                )
                await log_channel.send(embed=embed)
                break

