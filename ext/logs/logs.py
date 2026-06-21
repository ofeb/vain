from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from core.managers.values import color

if TYPE_CHECKING:
    pass

EVENT_TYPES = {
    "messages": "Message edit/delete logging",
    "members": "Member join/leave/nickname logging",
    "channels": "Channel create/delete/update logging",
    "roles": "Role create/delete/update logging",
    "invites": "Invite create/delete logging",
    "emojis": "Emoji/sticker create/delete/update logging",
    "voice": "Voice channel join/leave/move logging",
}


class Logs(commands.Cog):
    """Server logging for events like messages, members, and moderation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_webhook(self, guild_id: int, channel_id: int) -> Optional[discord.Webhook]:
        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return None
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.user and wh.user.id == self.bot.user.id:
                    return wh
            wh = await channel.create_webhook(name="Bleed Logs")
            return wh
        except Exception:
            return None

    async def _log(self, guild_id: int, event_type: str, embed: discord.Embed) -> None:
        try:
            rows = await self.bot.db.fetch(
                "SELECT channel_id, color FROM log_config WHERE guild_id = $1 AND $2 = ANY(events)",
                guild_id, event_type,
            )
            for row in rows:
                if row[1]:
                    try:
                        embed.color = discord.Color.from_str(row[1])
                    except Exception:
                        pass
                wh = await self._get_webhook(guild_id, row[0])
                if wh:
                    await wh.send(embed=embed, wait=False)
        except Exception:
            pass

    async def _is_ignored(self, guild_id: int, channel_id: int) -> bool:
        try:
            rows = await self.bot.db.fetch(
                "SELECT ignored_channels FROM log_config WHERE guild_id = $1",
                guild_id,
            )
            for row in rows:
                if channel_id in (row[0] or []):
                    return True
        except Exception:
            pass
        return False

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if await self._is_ignored(message.guild.id, message.channel.id):
            return
        embed = discord.Embed(
            title="Message Deleted",
            description=message.content or "*No text content*",
            color=0xFF4444,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="ID", value=message.id, inline=True)
        await self._log(message.guild.id, "messages", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if await self._is_ignored(before.guild.id, before.channel.id):
            return
        embed = discord.Embed(
            title="Message Edited",
            color=0xFFAA44,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Before", value=before.content[:1024] or "*No content*", inline=False)
        embed.add_field(name="After", value=after.content[:1024] or "*No content*", inline=False)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Jump", value=f"[Click]({after.jump_url})", inline=True)
        await self._log(before.guild.id, "messages", embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title="Member Joined",
            description=f"{member.mention} **{member}**",
            color=0x44FF44,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        await self._log(member.guild.id, "members", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title="Member Left",
            description=f"**{member}** ({member.mention})",
            color=0xFF4444,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        await self._log(member.guild.id, "members", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick:
            embed = discord.Embed(
                title="Nickname Changed",
                color=0xFFAA44,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.add_field(name="Before", value=before.nick or before.name, inline=True)
            embed.add_field(name="After", value=after.nick or after.name, inline=True)
            await self._log(after.guild.id, "members", embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        embed = discord.Embed(
            title="Channel Created",
            description=f"{channel.mention} `{channel.name}`",
            color=0x44FF44,
            timestamp=discord.utils.utcnow(),
        )
        channel_type = str(channel.type).title()
        if isinstance(channel, discord.VoiceChannel):
            channel_type = "Voice channel"
        elif isinstance(channel, discord.TextChannel):
            channel_type = "Text channel"
        elif isinstance(channel, discord.CategoryChannel):
            channel_type = "Category channel"
        embed.add_field(name="Type", value=channel_type, inline=True)
        embed.add_field(name="ID", value=channel.id, inline=True)
        await self._log(channel.guild.id, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        embed = discord.Embed(
            title="Channel Deleted",
            description=f"`{channel.name}`",
            color=0xFF4444,
            timestamp=discord.utils.utcnow(),
        )
        channel_type = str(channel.type).title()
        if isinstance(channel, discord.VoiceChannel):
            channel_type = "Voice channel"
        elif isinstance(channel, discord.TextChannel):
            channel_type = "Text channel"
        elif isinstance(channel, discord.CategoryChannel):
            channel_type = "Category channel"
        embed.add_field(name="Type", value=channel_type, inline=True)
        embed.add_field(name="ID", value=channel.id, inline=True)
        await self._log(channel.guild.id, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` -> `{after.name}`")
        if isinstance(before, discord.TextChannel):
            if before.topic != after.topic:
                changes.append(f"Topic: `{before.topic or 'None'}` -> `{after.topic or 'None'}`")
            if before.slowmode_delay != after.slowmode_delay:
                changes.append(f"Slowmode: `{before.slowmode_delay}s` -> `{after.slowmode_delay}s`")
        elif isinstance(before, discord.VoiceChannel):
            if before.bitrate != after.bitrate:
                changes.append(f"Bitrate: `{before.bitrate}` -> `{after.bitrate}`")
            if before.user_limit != after.user_limit:
                changes.append(f"User Limit: `{before.user_limit}` -> `{after.user_limit}`")

        if not changes:
            return

        embed = discord.Embed(
            title="Channel Updated",
            description=after.mention,
            color=0xFFAA44,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Changes", value="\n".join(changes), inline=False)
        await self._log(after.guild.id, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = discord.Embed(
            title="Role Created",
            description=role.mention,
            color=0x44FF44,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Name", value=role.name, inline=True)
        embed.add_field(name="ID", value=role.id, inline=True)
        await self._log(role.guild.id, "roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = discord.Embed(
            title="Role Deleted",
            description=f"`{role.name}`",
            color=0xFF4444,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=role.id, inline=True)
        await self._log(role.guild.id, "roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` -> `{after.name}`")
        if before.color != after.color:
            changes.append(f"Color: `{before.color}` -> `{after.color}`")
        if before.permissions != after.permissions:
            changes.append("Permissions updated")

        if not changes:
            return

        embed = discord.Embed(
            title="Role Updated",
            description=after.mention,
            color=0xFFAA44,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Changes", value="\n".join(changes), inline=False)
        await self._log(after.guild.id, "roles", embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return

        if before.channel != after.channel:
            if before.channel is None:
                embed = discord.Embed(
                    title="Voice Join",
                    description=f"{member.mention} joined {after.channel.mention}",
                    color=0x44FF44,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                await self._log(member.guild.id, "voice", embed)
            elif after.channel is None:
                embed = discord.Embed(
                    title="Voice Leave",
                    description=f"{member.mention} left {before.channel.mention}",
                    color=0xFF4444,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                await self._log(member.guild.id, "voice", embed)
            else:
                embed = discord.Embed(
                    title="Voice Move",
                    description=f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}",
                    color=0xFFAA44,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                await self._log(member.guild.id, "voice", embed)

        changes = []
        if before.self_mute != after.self_mute:
            if after.self_mute:
                changes.append("Muted themselves")
            else:
                changes.append("Unmuted themselves")
        if before.mute != after.mute:
            if after.mute:
                changes.append("Got muted by moderator")
            else:
                changes.append("Got unmuted by moderator")
        if before.self_deaf != after.self_deaf:
            if after.self_deaf:
                changes.append("Deafened themselves")
            else:
                changes.append("Undeafened themselves")
        if before.deaf != after.deaf:
            if after.deaf:
                changes.append("Got deafened by moderator")
            else:
                changes.append("Got undeafened by moderator")
        if before.suppress != after.suppress:
            if after.suppress:
                changes.append("Suppressed")
            else:
                changes.append("Unsuppressed")

        if changes:
            embed = discord.Embed(
                title="Voice State Updated",
                description=f"{member.mention} — " + ", ".join(changes),
                color=0xFFAA44,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            await self._log(member.guild.id, "voice", embed)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]) -> None:
        before_ids = {e.id for e in before}
        after_ids = {e.id for e in after}

        for emoji in after:
            if emoji.id not in before_ids:
                embed = discord.Embed(
                    title="Emoji Created",
                    description=f"{emoji} `:{emoji.name}:`",
                    color=0x44FF44,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_thumbnail(url=emoji.url)
                embed.add_field(name="ID", value=emoji.id, inline=True)
                await self._log(guild.id, "emojis", embed)

        for emoji in before:
            if emoji.id not in after_ids:
                embed = discord.Embed(
                    title="Emoji Deleted",
                    description=f"`:{emoji.name}:`",
                    color=0xFF4444,
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name="ID", value=emoji.id, inline=True)
                await self._log(guild.id, "emojis", embed)

    @commands.Cog.listener()
    async def on_guild_member_remove(self, member: discord.Member) -> None:
        try:
            audit_log = [entry async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.ban)]
            if audit_log and audit_log[0].target.id == member.id:
                embed = discord.Embed(
                    title="Member Banned",
                    description=f"**{member}** ({member.mention})",
                    color=0xFF4444,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                if audit_log[0].reason:
                    embed.add_field(name="Reason", value=audit_log[0].reason, inline=False)
                if audit_log[0].user:
                    embed.add_field(name="Moderator", value=str(audit_log[0].user), inline=True)
                await self._log(member.guild.id, "members", embed)
        except Exception:
            pass

    @group(
        name="logs",
        description="Configure server logging",
        invoke_without_command=True,
        aliases=["logging", "log"],
    )
    @has_permissions(manage_guild=True)
    async def logs(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @logs.command(
        name="add",
        description="Enable logging for an event type in a channel",
    )
    @describe(channel="Channel to send logs to", event="Event type to log")
    @has_permissions(manage_guild=True)
    async def logs_add(self, ctx: Context, channel: discord.TextChannel, event: str = None) -> None:
        if event is None:
            events = list(EVENT_TYPES.keys())
        else:
            event = event.lower()
            if event not in EVENT_TYPES:
                await ctx.fail(f"Invalid event type. Valid: {', '.join(EVENT_TYPES.keys())}")
                return
            events = [event]

        for evt in events:
            try:
                await self.bot.db.execute(
                    """INSERT INTO log_config (guild_id, channel_id, events)
                       VALUES ($1, $2, ARRAY[$3])
                       ON CONFLICT (guild_id, channel_id) DO UPDATE
                       SET events = array_append(log_config.events, $3)
                       WHERE NOT (log_config.events @> ARRAY[$3])""",
                    ctx.guild.id, channel.id, evt,
                )
            except Exception:
                pass

        return await ctx.success(f"Logging enabled for **{len(events)}** event(s) in {channel.mention}")

    @logs.command(
        name="remove",
        description="Disable logging for an event type",
    )
    @describe(channel="Log channel", event="Event type to disable")
    @has_permissions(manage_guild=True)
    async def logs_remove(self, ctx: Context, channel: discord.TextChannel, event: str = None) -> None:
        if event is None:
            try:
                await self.bot.db.execute(
                    "DELETE FROM log_config WHERE guild_id = $1 AND channel_id = $2",
                    ctx.guild.id, channel.id,
                )
                return await ctx.success(f"**All** logging disabled in {channel.mention}")
            except Exception:
                await ctx.fail("Failed to update logging configuration.")
                return

        event = event.lower()
        try:
            await self.bot.db.execute(
                "UPDATE log_config SET events = array_remove(events, $1) WHERE guild_id = $2 AND channel_id = $3",
                event, ctx.guild.id, channel.id,
            )
            await ctx.success(f"`{event}` logging disabled in {channel.mention}")
        except Exception:
            await ctx.fail("Failed to update logging configuration.")

    @logs.command(
        name="config",
        description="View current logging configuration",
        aliases=["settings", "list"],
    )
    @has_permissions(manage_guild=True)
    async def logs_config(self, ctx: Context) -> None:
        try:
            rows = await self.bot.db.fetch(
                "SELECT channel_id, events, color FROM log_config WHERE guild_id = $1",
                ctx.guild.id,
            )
            if not rows:
                await ctx.fail("No logging configuration found.")
                return

            embed = discord.Embed(
                title="Logging Configuration",
                color=color.base,
            )
            for row in rows:
                channel = ctx.guild.get_channel(row[0])
                if channel:
                    events = ", ".join(f"`{e}`" for e in row[1])
                    color_val = row[2] or "default"
                    embed.add_field(name=f"{channel.mention} ({color_val})", value=events, inline=False)
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Configuration unavailable.")

    @logs.command(
        name="color",
        description="Set the embed color for log messages",
        aliases=["colour"],
    )
    @describe(hex="Hex color code (e.g. #FF0000)")
    @has_permissions(manage_guild=True)
    async def logs_color(self, ctx: Context, *, hex: str = None) -> None:
        if hex is None:
            return await ctx.fail("Provide a hex color code. Example: `,logs color #FF0000`")

        try:
            color_val = discord.Color.from_str(hex)
            
            await self.bot.db.execute(
                "UPDATE log_config SET color = $1 WHERE guild_id = $2",
                hex, ctx.guild.id,
            )
            embed = discord.Embed(
                title="Log Color Updated",
                description=f"Log embed color set to `{hex}`.",
                color=color_val,
            )
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Invalid color format. Use hex like `#FF0000`.")

    @logs.command(
        name="ignore",
        description="Ignore a channel from being logged",
    )
    @describe(channel="Channel to ignore")
    @has_permissions(manage_guild=True)
    async def logs_ignore_add(self, ctx: Context, channel: discord.TextChannel) -> None:
        try:
            await self.bot.db.execute(
                """UPDATE log_config SET ignored_channels = array_append(ignored_channels, $1)
                   WHERE guild_id = $2 AND NOT (ignored_channels @> ARRAY[$1])""",
                channel.id, ctx.guild.id,
            )
            embed = discord.Embed(
                title="Channel Ignored",
                description=f"{channel.mention} will no longer be logged.",
                color=color.base,
            )
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Failed to ignore channel.")

    @logs.command(
        name="unignore",
        description="Unignore a channel from being logged",
    )
    @describe(channel="Channel to unignore")
    @has_permissions(manage_guild=True)
    async def logs_ignore_remove(self, ctx: Context, channel: discord.TextChannel) -> None:
        try:
            await self.bot.db.execute(
                "UPDATE log_config SET ignored_channels = array_remove(ignored_channels, $1) WHERE guild_id = $2",
                channel.id, ctx.guild.id,
            )
            embed = discord.Embed(
                title="Channel Unignored",
                description=f"{channel.mention} will now be logged.",
                color=color.base,
            )
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Failed to unignore channel.")

    @logs.command(
        name="ignorelist",
        description="View all ignored channels",
        aliases=["ignored"],
    )
    @has_permissions(manage_guild=True)
    async def logs_ignore_list(self, ctx: Context) -> None:
        try:
            rows = await self.bot.db.fetch(
                "SELECT ignored_channels FROM log_config WHERE guild_id = $1",
                ctx.guild.id,
            )
            all_ignored = set()
            for row in rows:
                if row[0]:
                    all_ignored.update(row[0])

            if not all_ignored:
                await ctx.fail("No channels are **ignored** from logging.")
                return

            lines = []
            for cid in all_ignored:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    lines.append(ch.mention)

            numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
            return await ctx.paginate(
                discord.Embed(title="Ignored Log Channels", color=color.base).set_author(
                    name=str(ctx.author), icon_url=ctx.author.display_avatar.url
                ),
                numbered,
            )
        except Exception:
            await ctx.fail("Failed to fetch ignored channels.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
