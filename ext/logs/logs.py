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
                "SELECT channel_id FROM log_config WHERE guild_id = $1 AND $2 = ANY(events)",
                guild_id, event_type,
            )
            for row in rows:
                wh = await self._get_webhook(guild_id, row[0])
                if wh:
                    await wh.send(embed=embed, wait=False)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
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
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
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
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="ID", value=channel.id, inline=True)
        await self._log(channel.guild.id, "channels", embed)

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
    async def logs_add(self, ctx: Context, channel: discord.TextChannel, event: str) -> None:
        event = event.lower()
        if event not in EVENT_TYPES:
            await ctx.fail(f"Invalid event type. Valid: {', '.join(EVENT_TYPES.keys())}")
            return

        try:
            await self.bot.db.execute(
                """INSERT INTO log_config (guild_id, channel_id, events)
                   VALUES ($1, $2, ARRAY[$3])
                   ON CONFLICT (guild_id, channel_id) DO UPDATE
                   SET events = array_append(log_config.events, $3)
                   WHERE NOT (log_config.events @> ARRAY[$3])""",
                ctx.guild.id, channel.id, event,
            )
            await ctx.success(f"`{event}` logging enabled in {channel.mention}")
        except Exception:
            await ctx.fail("Failed to configure logging.")

    @logs.command(
        name="remove",
        description="Disable logging for an event type",
    )
    @describe(channel="Log channel", event="Event type to disable")
    @has_permissions(manage_guild=True)
    async def logs_remove(self, ctx: Context, channel: discord.TextChannel, event: str) -> None:
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
                "SELECT channel_id, events FROM log_config WHERE guild_id = $1",
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
                    embed.add_field(name=channel.mention, value=events, inline=False)
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Configuration unavailable.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
