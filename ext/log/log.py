from __future__ import annotations

import contextlib
import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord
from discord.ext.commands import group

from core.discord.ctx import Context
from core.discord.package import Package

from .events import LogEvents
from core.managers.permissions import has_permissions
from core.managers.values import color, emojis

if TYPE_CHECKING:
    from core.vain import Vain

EVENT_TYPES = {
    "messages": "Message edit/delete logging",
    "members": "Member join/leave/timeout/ban/kick logging",
    "channels": "Channel create/delete/update logging",
    "roles": "Role create/delete/update logging",
    "invites": "Invite create/delete logging",
    "emojis": "Emoji/sticker create/delete/update logging",
    "voice": "Voice channel join/leave/mute/deafen logging",
}

PERMISSION_NAMES = {
    "create_instant_invite": "Create Invite",
    "kick_members": "Kick Members",
    "ban_members": "Ban Members",
    "administrator": "Administrator",
    "manage_channels": "Manage Channels",
    "manage_guild": "Manage Guild",
    "add_reactions": "Add Reactions",
    "view_audit_log": "View Audit Log",
    "priority_speaker": "Priority Speaker",
    "stream": "Stream",
    "view_channel": "Read Messages",
    "read_messages": "Read Messages",
    "send_messages": "Send Messages",
    "send_tts_messages": "Send TTS Messages",
    "manage_messages": "Manage Messages",
    "embed_links": "Embed Links",
    "attach_files": "Attach Files",
    "read_message_history": "Read Message History",
    "mention_everyone": "Mention Everyone",
    "external_emojis": "Use External Emojis",
    "use_external_emojis": "Use External Emojis",
    "view_guild_insights": "View Guild Insights",
    "connect": "Connect",
    "speak": "Speak",
    "mute_members": "Mute Members",
    "deafen_members": "Deafen Members",
    "move_members": "Move Members",
    "use_voice_activation": "Use Voice Activity",
    "change_nickname": "Change Nickname",
    "manage_nicknames": "Manage Nicknames",
    "manage_roles": "Manage Roles",
    "manage_webhooks": "Manage Webhooks",
    "manage_expressions": "Manage Expressions",
    "use_application_commands": "Use Application Commands",
    "request_to_speak": "Request to Speak",
    "manage_events": "Manage Events",
    "manage_threads": "Manage Threads",
    "create_public_threads": "Create Public Threads",
    "create_private_threads": "Create Private Threads",
    "external_stickers": "Use External Stickers",
    "use_external_stickers": "Use External Stickers",
    "send_messages_in_threads": "Send Messages in Threads",
    "use_embedded_activities": "Use Activities",
    "moderate_members": "Moderate Members",
    "use_soundboard": "Use Soundboard",
    "create_expressions": "Create Expressions",
    "send_voice_messages": "Send Voice Messages",
}


class Log(LogEvents, Package):
    """Server logging via webhooks matching Vain's format."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._webhook_cache: dict[int, discord.Webhook] = {}

    async def _get_webhook(self, channel_id: int) -> Optional[discord.Webhook]:
        if channel_id in self._webhook_cache:
            wh = self._webhook_cache[channel_id]
            try:
                await wh.send("", wait=False)
            except discord.NotFound:
                del self._webhook_cache[channel_id]
            except discord.HTTPException:
                return wh
            else:
                return wh

        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None
        target = channel.parent if isinstance(channel, discord.Thread) else channel
        if not isinstance(target, discord.TextChannel):
            return None
        try:
            webhooks = await target.webhooks()
            for wh in webhooks:
                if wh.user and wh.user.id == self.bot.user.id and wh.name == "vain logs":
                    self._webhook_cache[channel_id] = wh
                    return wh
            wh = await target.create_webhook(
                name="vain logs",
                avatar=await self.bot.user.display_avatar.read(),
            )
            self._webhook_cache[channel_id] = wh
            return wh
        except (discord.Forbidden, discord.HTTPException):
            return None

    async def _get_event_color(self, guild_id: int, channel_id: int, event: str) -> Optional[int]:
        try:
            row = await self.db.fetchval(
                "SELECT color FROM log_event_colors WHERE guild_id = $1 AND channel_id = $2 AND event = $3",
                guild_id, channel_id, event,
            )
            if row:
                return int(row.lstrip("#"), 16)
        except Exception:
            pass

        try:
            row = await self.db.fetchval(
                "SELECT color FROM log_config WHERE guild_id = $1 AND channel_id = $2",
                guild_id, channel_id,
            )
            if row:
                return int(row.lstrip("#"), 16)
        except Exception:
            pass
        return None

    async def _is_ignored(self, guild_id: int, target_id: int) -> bool:
        try:
            result = await self.db.fetchval(
                "SELECT 1 FROM log_ignored WHERE guild_id = $1 AND target_id = $2 LIMIT 1",
                guild_id, target_id,
            )
            return bool(result)
        except Exception:
            return False

    async def _log(self, guild_id: int, event_type: str, embed: discord.Embed) -> None:
        try:
            rows = await self.db.fetch(
                "SELECT channel_id FROM log_config WHERE guild_id = $1 AND $2 = ANY(events)",
                guild_id, event_type,
            )
            for row in rows:
                channel_id = row[0]
                custom_color = await self._get_event_color(guild_id, channel_id, event_type)
                if custom_color is not None:
                    embed.color = custom_color
                wh = await self._get_webhook(channel_id)
                if wh:
                    with contextlib.suppress(discord.HTTPException):
                        await wh.send(embed=embed, username="vain logs")
        except Exception:
            pass

    @group(
        name="log",
        description="Set up logging for your community",
        invoke_without_command=True,
        aliases=["logging", "logger", "logs"],
    )
    @has_permissions(manage_guild=True)
    async def log(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @log.command(
        name="add",
        description="Set up logging in a channel",
        example=",log add #logs messages",
    )
    @has_permissions(manage_guild=True)
    async def log_add(self, ctx: Context, channel: discord.TextChannel, event: str = None) -> None:
        if event is None:
            events = list(EVENT_TYPES.keys())
        else:
            event = event.lower()
            if event == "all":
                events = list(EVENT_TYPES.keys())
            elif event not in EVENT_TYPES:
                return await ctx.warn(f"Invalid event type. Valid: {', '.join(f'`{e}`' for e in EVENT_TYPES)}")
            else:
                events = [event]

        for evt in events:
            with contextlib.suppress(Exception):
                await self.db.execute(
                    """INSERT INTO log_config (guild_id, channel_id, events)
                       VALUES ($1, $2, ARRAY[$3])
                       ON CONFLICT (guild_id, channel_id) DO UPDATE
                       SET events = array_append(log_config.events, $3)
                       WHERE NOT (log_config.events @> ARRAY[$3])""",
                    ctx.guild.id, channel.id, evt,
                )

        label = "all events" if len(events) > 1 else f"`{events[0]}`"
        return await ctx.success(f"Event {label} will be **logged** in {channel.mention}")

    @log.command(
        name="remove",
        description="Remove events from a logging channel",
        example=",log remove #logs messages",
    )
    @has_permissions(manage_guild=True)
    async def log_remove(self, ctx: Context, channel: discord.TextChannel, event: str = None) -> None:
        if event is None or event.lower() == "all":
            await self.db.execute(
                "DELETE FROM log_config WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id, channel.id,
            )
            self._webhook_cache.pop(channel.id, None)
            return await ctx.success(f"No longer **logging** any events to {channel.mention}")

        event = event.lower()
        if event not in EVENT_TYPES:
            return await ctx.warn(f"Invalid event type. Valid: {', '.join(f'`{e}`' for e in EVENT_TYPES)}")

        await self.db.execute(
            "UPDATE log_config SET events = array_remove(events, $1) WHERE guild_id = $2 AND channel_id = $3",
            event, ctx.guild.id, channel.id,
        )
        return await ctx.success(f"No longer **logging** event `{event}` to {channel.mention}")

    @log.group(
        name="color",
        description="Customize embed color for an event",
        invoke_without_command=True,
        example=",log color #logs messages ff0000",
    )
    @has_permissions(manage_guild=True)
    async def log_color(self, ctx: Context, channel: discord.TextChannel = None, event: str = None, *, hex_color: str = None) -> None:
        if channel is None or event is None or hex_color is None:
            return await ctx.send_help(ctx.command)

        event = event.lower()
        if event not in EVENT_TYPES:
            return await ctx.warn(f"Invalid event type. Valid: {', '.join(f'`{e}`' for e in EVENT_TYPES)}")

        hex_color = hex_color.strip("#")
        try:
            int(hex_color, 16)
        except ValueError:
            return await ctx.warn("Invalid hex color code")

        await self.db.execute(
            """INSERT INTO log_event_colors (guild_id, channel_id, event, color)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (guild_id, channel_id, event) DO UPDATE SET color = $4""",
            ctx.guild.id, channel.id, event, hex_color,
        )
        return await ctx.success(f"Log color for `{event}` in {channel.mention} set to `#{hex_color}`")

    @log_color.command(
        name="list",
        description="List embed color customization for events",
        example=",log color list #logs",
    )
    @has_permissions(manage_guild=True)
    async def log_color_list(self, ctx: Context, channel: discord.TextChannel = None) -> None:
        if channel is None:
            return await ctx.send_help(ctx.command)

        rows = await self.db.fetch(
            "SELECT event, color FROM log_event_colors WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id, channel.id,
        )
        if not rows:
            return await ctx.warn(f"No custom colors set for {channel.mention}")

        lines = [f"`{row[0]}` — `#{row[1]}`" for row in rows]
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            discord.Embed(title=f"Log Colors for #{channel.name}", color=self.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @log.group(
        name="ignore",
        description="Ignore a member or channel from being logged",
        invoke_without_command=True,
        example=",log ignore jonathan",
    )
    @has_permissions(manage_guild=True)
    async def log_ignore(self, ctx: Context, target: Union[discord.Member, discord.TextChannel, discord.VoiceChannel] = None) -> None:
        if target is None:
            return await ctx.send_help(ctx.command)

        existing = await self.db.fetchval(
            "SELECT 1 FROM log_ignored WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id, target.id,
        )
        if existing:
            return await ctx.warn(f"{target.mention} is already **ignored** from logging")

        target_type = "member" if isinstance(target, discord.Member) else "channel"
        await self.db.execute(
            "INSERT INTO log_ignored (guild_id, target_id, target_type) VALUES ($1, $2, $3)",
            ctx.guild.id, target.id, target_type,
        )
        return await ctx.success(f"{target.mention} will be **ignored** from logging")

    @log_ignore.command(
        name="remove",
        description="Remove an ignored member or channel",
        example=",log ignore remove jonathan",
    )
    @has_permissions(manage_guild=True)
    async def log_ignore_remove(self, ctx: Context, target: Union[discord.Member, discord.TextChannel, discord.VoiceChannel] = None) -> None:
        if target is None:
            return await ctx.send_help(ctx.command)

        deleted = await self.db.execute(
            "DELETE FROM log_ignored WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id, target.id,
        )
        if deleted == "DELETE 0":
            return await ctx.warn(f"{target.mention} is not **ignored**")
        return await ctx.success(f"{target.mention} is no longer **ignored** from logging")

    @log_ignore.command(
        name="list",
        description="View all ignored members and channels",
        aliases=["ls", "show", "view"],
    )
    @has_permissions(manage_guild=True)
    async def log_ignore_list(self, ctx: Context) -> None:
        rows = await self.db.fetch(
            "SELECT target_id, target_type FROM log_ignored WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No members or channels are **ignored** from logging")

        lines = []
        for row in rows:
            if row[1] == "member":
                obj = ctx.guild.get_member(row[0])
            else:
                obj = ctx.guild.get_channel(row[0])
            if obj:
                lines.append(f"{obj.mention} ({row[1]})")

        if not lines:
            return await ctx.warn("No valid ignored entries found")

        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            discord.Embed(title="Ignored Log Targets", color=self.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @log.command(
        name="list",
        description="View current logging configuration",
        aliases=["config", "settings", "show"],
    )
    @has_permissions(manage_guild=True)
    async def log_list(self, ctx: Context) -> None:
        rows = await self.db.fetch(
            "SELECT channel_id, events FROM log_config WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No logging configuration found")

        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(row[0])
            if channel:
                events_str = ", ".join(f"`{e}`" for e in row[1])
                lines.append(f"{channel.mention} — {events_str}")

        if not lines:
            return await ctx.warn("No valid logging channels found")

        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            discord.Embed(title="Logging Configuration", color=self.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )


async def setup(bot: Vain):
    await bot.add_cog(Log(bot))
