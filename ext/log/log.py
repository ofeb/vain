from __future__ import annotations

import contextlib
import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord
from discord.ext.commands import group

from core.discord.ctx import Context
from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.managers.values import color, emojis

if TYPE_CHECKING:
    from core.bleed import Bleed

EVENT_TYPES = {
    "messages": "Message edit/delete logging",
    "members": "Member join/leave/timeout/ban/kick logging",
    "channels": "Channel create/delete/update logging",
    "roles": "Role create/delete/update logging",
    "invites": "Invite create/delete logging",
    "emojis": "Emoji/sticker create/delete/update logging",
    "voice": "Voice channel join/leave/move/mute/deafen logging",
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


def _channel_type_label(channel: discord.abc.GuildChannel) -> str:
    if isinstance(channel, discord.VoiceChannel):
        return "Voice channel"
    if isinstance(channel, discord.TextChannel):
        return "Text channel"
    if isinstance(channel, discord.CategoryChannel):
        return "Category channel"
    if isinstance(channel, discord.ForumChannel):
        return "Forum channel"
    if isinstance(channel, discord.StageChannel):
        return "Stage channel"
    return str(channel.type).replace("_", " ").title() + " channel"


async def _get_audit_entry(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: int = None,
    *,
    limit: int = 5,
) -> Optional[discord.AuditLogEntry]:
    try:
        async for entry in guild.audit_logs(limit=limit, action=action):
            if target_id is None or (entry.target and entry.target.id == target_id):
                if (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                    return entry
    except (discord.Forbidden, discord.HTTPException):
        pass
    return None


def _format_overwrite_changes(
    old: Optional[discord.PermissionOverwrite],
    new: Optional[discord.PermissionOverwrite],
) -> list[str]:
    old = old or discord.PermissionOverwrite()
    new = new or discord.PermissionOverwrite()
    changes = []
    for name, label in PERMISSION_NAMES.items():
        old_val = getattr(old, name, None)
        new_val = getattr(new, name, None)
        if old_val != new_val:
            old_str = str(old_val) if old_val is not None else "inherit"
            new_str = str(new_val) if new_val is not None else "inherit"
            changes.append(f"**{label}**: `{old_str}` -> `{new_str}`")
    return changes


class Log(Package):
    """Server logging via webhooks matching bleed's format."""

    def __init__(self, bot: Bleed):
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
                if wh.user and wh.user.id == self.bot.user.id and wh.name == "bleed logs":
                    self._webhook_cache[channel_id] = wh
                    return wh
            wh = await target.create_webhook(
                name="bleed logs",
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
                        await wh.send(embed=embed, username="bleed logs")
        except Exception:
            pass

    @Package.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if await self._is_ignored(message.guild.id, message.channel.id):
            return
        if await self._is_ignored(message.guild.id, message.author.id):
            return

        embed = discord.Embed(
            description=(
                f"Message from {message.author.mention} deleted in {message.channel.mention}\n"
                f"It was sent at <t:{int(message.created_at.timestamp())}>"
            ),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(
            name="Message Deleted",
            icon_url=message.author.display_avatar.url,
        )
        embed.set_footer(text=f"User ID: {message.author.id}")

        if message.content:
            embed.add_field(name="**Message Content**", value=message.content[:1024], inline=False)

        if message.attachments:
            urls = "\n".join(a.url for a in message.attachments[:5])
            embed.add_field(name="**Attachments**", value=urls[:1024], inline=False)

        await self._log(message.guild.id, "messages", embed)

    @Package.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if await self._is_ignored(before.guild.id, before.channel.id):
            return
        if await self._is_ignored(before.guild.id, before.author.id):
            return

        embed = discord.Embed(
            description=(
                f"Message from {before.author.mention} edited <t:{int(discord.utils.utcnow().timestamp())}:R>\n"
                f"[View the message in #{before.channel.name}]({after.jump_url})"
            ),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(
            name="Message Edited",
            icon_url=before.author.display_avatar.url,
        )
        embed.set_footer(text=f"User ID: {before.author.id}")
        embed.add_field(name="**Before**", value=before.content[:1024] or "*empty*", inline=False)
        embed.add_field(name="**After**", value=after.content[:1024] or "*empty*", inline=False)

        await self._log(before.guild.id, "messages", embed)

    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if await self._is_ignored(member.guild.id, member.id):
            return

        embed = discord.Embed(
            description=f"{member.mention} joined the server\nAccount created <t:{int(member.created_at.timestamp())}:R>",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Member Joined", icon_url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        embed.set_thumbnail(url=member.display_avatar.url)

        await self._log(member.guild.id, "members", embed)

    @Package.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if await self._is_ignored(member.guild.id, member.id):
            return

        entry = await _get_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if entry:
            embed = discord.Embed(
                description=f"{member.mention} was kicked from the server",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Member Kicked", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            if entry.user:
                embed.add_field(
                    name="**Moderator**",
                    value=f"{entry.user.mention} (`{entry.user.id}`)",
                    inline=True,
                )
            if entry.reason:
                embed.add_field(name="**Reason**", value=entry.reason, inline=True)
            await self._log(member.guild.id, "members", embed)
            return

        embed = discord.Embed(
            description=f"{member.mention} left the server",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Member Left", icon_url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        if member.joined_at:
            embed.add_field(
                name="**Joined**",
                value=f"<t:{int(member.joined_at.timestamp())}:R>",
                inline=True,
            )

        await self._log(member.guild.id, "members", embed)

    @Package.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.bot:
            return
        if await self._is_ignored(after.guild.id, after.id):
            return

        if before.nick != after.nick:
            embed = discord.Embed(
                description=f"{after.mention} nickname changed",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Nickname Changed", icon_url=after.display_avatar.url)
            embed.set_footer(text=f"User ID: {after.id}")
            embed.add_field(name="**Before**", value=before.nick or before.name, inline=True)
            embed.add_field(name="**After**", value=after.nick or after.name, inline=True)
            await self._log(after.guild.id, "members", embed)

        if before.communication_disabled_until != after.communication_disabled_until:
            if after.communication_disabled_until and after.communication_disabled_until > discord.utils.utcnow():
                embed = discord.Embed(
                    description=f"{after.mention} timed out until <t:{int(after.communication_disabled_until.timestamp())}> (<t:{int(after.communication_disabled_until.timestamp())}:R>)",
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name="Member Timed Out", icon_url=after.display_avatar.url)
                embed.set_footer(text=f"User ID: {after.id}")
                entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_update, after.id)
                if entry and entry.user:
                    embed.add_field(
                        name="**Moderator**",
                        value=f"{entry.user.mention} (`{entry.user.id}`)",
                        inline=True,
                    )
                await self._log(after.guild.id, "members", embed)
            elif before.communication_disabled_until and (
                not after.communication_disabled_until
                or after.communication_disabled_until <= discord.utils.utcnow()
            ):
                embed = discord.Embed(
                    description=f"{after.mention} timeout removed early",
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name="Member Timed Out", icon_url=after.display_avatar.url)
                embed.set_footer(text=f"User ID: {after.id}")
                entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_update, after.id)
                if entry and entry.user:
                    embed.add_field(
                        name="**Moderator**",
                        value=f"{entry.user.mention} (`{entry.user.id}`)",
                        inline=True,
                    )
                await self._log(after.guild.id, "members", embed)

        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)

        for role in added:
            if role.is_default():
                continue
            embed = discord.Embed(
                description=f"{after.mention} was granted {role.mention}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Member Roles Updated", icon_url=after.display_avatar.url)
            embed.set_footer(text=f"User ID: {after.id}")
            entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_role_update, after.id)
            if entry and entry.user:
                if entry.user.id == after.id:
                    embed.add_field(
                        name="**Self-Assigned**",
                        value=f"{after.mention} (`{after.id}`)",
                        inline=True,
                    )
                else:
                    embed.add_field(
                        name="**Moderator**",
                        value=f"{entry.user.mention} (`{entry.user.id}`)",
                        inline=True,
                    )
            await self._log(after.guild.id, "roles", embed)

        for role in removed:
            if role.is_default():
                continue
            embed = discord.Embed(
                description=f"{after.mention} was removed from {role.mention}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Member Roles Updated", icon_url=after.display_avatar.url)
            embed.set_footer(text=f"User ID: {after.id}")
            entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_role_update, after.id)
            if entry and entry.user:
                if entry.user.id == after.id:
                    embed.add_field(
                        name="**Self-Assigned**",
                        value=f"{after.mention} (`{after.id}`)",
                        inline=True,
                    )
                else:
                    embed.add_field(
                        name="**Moderator**",
                        value=f"{entry.user.mention} (`{entry.user.id}`)",
                        inline=True,
                    )
            await self._log(after.guild.id, "roles", embed)

    @Package.listener()
    async def on_member_ban(self, guild: discord.Guild, user: Union[discord.User, discord.Member]) -> None:
        if await self._is_ignored(guild.id, user.id):
            return

        embed = discord.Embed(
            description=f"{user.mention} was banned from the server",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Member Banned", icon_url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")

        entry = await _get_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if entry:
            if entry.user:
                embed.add_field(
                    name="**Moderator**",
                    value=f"{entry.user.mention} (`{entry.user.id}`)",
                    inline=True,
                )
            if entry.reason:
                embed.add_field(name="**Reason**", value=entry.reason, inline=True)

        await self._log(guild.id, "members", embed)

    @Package.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = discord.Embed(
            description=f"{user.mention} was unbanned from the server",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Member Unbanned", icon_url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")

        entry = await _get_audit_entry(guild, discord.AuditLogAction.unban, user.id)
        if entry and entry.user:
            embed.add_field(
                name="**Moderator**",
                value=f"{entry.user.mention} (`{entry.user.id}`)",
                inline=True,
            )

        await self._log(guild.id, "members", embed)

    @Package.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = discord.Embed(
            description=f"Role {role.mention} created",
            timestamp=discord.utils.utcnow(),
            color=role.color.value if role.color.value else 0x262626,
        )

        entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        if entry and entry.user:
            embed.description = f"Role {role.mention} created by {entry.user.mention}"
            embed.set_author(name="Role Created", icon_url=entry.user.display_avatar.url)
            embed.set_footer(text=f"User ID: {entry.user.id}")
        else:
            embed.set_author(name="Role Created")

        embed.add_field(name="**Name**", value=role.name, inline=True)
        embed.add_field(name="**Color**", value=f"`#{role.color.value:06x}`", inline=True)

        await self._log(role.guild.id, "roles", embed)

    @Package.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = discord.Embed(
            description=f"Role **{role.name}** deleted",
            timestamp=discord.utils.utcnow(),
        )

        entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        if entry and entry.user:
            embed.description = f"Role **{role.name}** deleted by {entry.user.mention}"
            embed.set_author(name="Role Deleted", icon_url=entry.user.display_avatar.url)
            embed.set_footer(text=f"User ID: {entry.user.id}")
        else:
            embed.set_author(name="Role Deleted")

        embed.add_field(
            name="**Created**",
            value=f"<t:{int(role.created_at.timestamp())}:F> (<t:{int(role.created_at.timestamp())}:R>)",
            inline=True,
        )

        await self._log(role.guild.id, "roles", embed)

    @Package.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        changes = []

        entry = await _get_audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        moderator = entry.user if entry else None

        if before.name != after.name:
            changes.append(("**Name**", f"{before.name} -> {after.name}", True))

        if before.color != after.color:
            changes.append(("**Color**", f"`#{before.color.value:06x}` -> `#{after.color.value:06x}`", True))

        if before.hoist != after.hoist:
            changes.append(("**Hoisted**", f"`{before.hoist}` -> `{after.hoist}`", True))

        if before.mentionable != after.mentionable:
            changes.append(("**Mentionable**", f"`{before.mentionable}` -> `{after.mentionable}`", True))

        if before.permissions != after.permissions:
            perm_changes = []
            before_perms = dict(before.permissions)
            after_perms = dict(after.permissions)
            for perm, after_val in after_perms.items():
                before_val = before_perms.get(perm, False)
                if before_val != after_val:
                    label = PERMISSION_NAMES.get(perm, perm.replace("_", " ").title())
                    if after_val:
                        perm_changes.append(f"``✅`` {label}")
                    else:
                        perm_changes.append(f"``❌`` {label}")
            if perm_changes:
                changes.append(("**Permissions Updated**", "\n".join(perm_changes), False))

        if not changes:
            return

        embed = discord.Embed(
            description=f"Role {after.mention} updated" + (f" by {moderator.mention}" if moderator else ""),
            timestamp=discord.utils.utcnow(),
        )
        if moderator:
            embed.set_author(name="Role Updated", icon_url=moderator.display_avatar.url)
            embed.set_footer(text=f"User ID: {moderator.id}")
        else:
            embed.set_author(name="Role Updated")

        for name, value, inline in changes:
            embed.add_field(name=name, value=value, inline=inline)

        await self._log(after.guild.id, "roles", embed)

    @Package.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        label = _channel_type_label(channel)
        embed = discord.Embed(
            description=f"{label} {channel.mention} created",
            timestamp=discord.utils.utcnow(),
        )

        entry = await _get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if entry and entry.user:
            embed.description = f"{label} {channel.mention} created by {entry.user.mention}"
            embed.set_author(name="Channel Created", icon_url=entry.user.display_avatar.url)
            embed.set_footer(text=f"User ID: {entry.user.id}")
        else:
            embed.set_author(name="Channel Created")

        await self._log(channel.guild.id, "channels", embed)

    @Package.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        label = _channel_type_label(channel)
        embed = discord.Embed(
            description=f"{label} **#{channel.name}** deleted",
            timestamp=discord.utils.utcnow(),
        )

        entry = await _get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if entry and entry.user:
            embed.description = (
                f"{label} **#{channel.name}** deleted by {entry.user.mention}\n"
                f"Channel was created at <t:{int(channel.created_at.timestamp())}:F> (<t:{int(channel.created_at.timestamp())}:R>)"
            )
            embed.set_author(name="Channel Deleted", icon_url=entry.user.display_avatar.url)
            embed.set_footer(text=f"User ID: {entry.user.id}")
        else:
            embed.description += f"\nChannel was created at <t:{int(channel.created_at.timestamp())}:F> (<t:{int(channel.created_at.timestamp())}:R>)"
            embed.set_author(name="Channel Deleted")

        await self._log(channel.guild.id, "channels", embed)

    @Package.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        changes = []
        label = _channel_type_label(after)

        if before.name != after.name:
            changes.append(f"**Name**: {before.name} -> {after.name}")

        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                old_topic = before.topic or "No topic"
                new_topic = after.topic or "No topic"
                changes.append(f"**Topic**: {old_topic} -> {new_topic}")
            if before.slowmode_delay != after.slowmode_delay:
                old_slow = f"{before.slowmode_delay}s" if before.slowmode_delay else "0"
                new_slow = f"{after.slowmode_delay}s" if after.slowmode_delay else "0"
                changes.append(f"**Slowmode Delay**: `{old_slow}` -> `{new_slow}`")
            if before.is_nsfw() != after.is_nsfw():
                changes.append(f"**NSFW**: `{before.is_nsfw()}` -> `{after.is_nsfw()}`")

        if isinstance(before, discord.VoiceChannel) and isinstance(after, discord.VoiceChannel):
            if before.bitrate != after.bitrate:
                changes.append(f"**Bitrate**: `{before.bitrate / 1000:.1f}kbps` -> `{after.bitrate / 1000:.1f}kbps`")
            if before.user_limit != after.user_limit:
                changes.append(f"**User Limit**: `{before.user_limit}` -> `{after.user_limit}`")

        if isinstance(before, discord.ForumChannel) and isinstance(after, discord.ForumChannel):
            old_tags = {t.name for t in before.available_tags}
            new_tags = {t.name for t in after.available_tags}
            added_tags = new_tags - old_tags
            removed_tags = old_tags - new_tags
            if added_tags:
                changes.append(f"**Tags Added**: {', '.join(added_tags)}")
            if removed_tags:
                changes.append(f"**Tags Removed**: {', '.join(removed_tags)}")

        if not changes:
            return

        entry = await _get_audit_entry(after.guild, discord.AuditLogAction.channel_update, after.id)
        moderator = entry.user if entry else None

        embed = discord.Embed(
            description=f"{label} {after.mention} updated" + (f" by {moderator.mention}" if moderator else ""),
            timestamp=discord.utils.utcnow(),
        )
        if moderator:
            embed.set_author(name="Channel Updated", icon_url=moderator.display_avatar.url)
            embed.set_footer(text=f"User ID: {moderator.id}")
        else:
            embed.set_author(name="Channel Updated")

        embed.add_field(name="**Changes**", value="\n".join(changes), inline=True)

        await self._log(after.guild.id, "channels", embed)

    @Package.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        if await self._is_ignored(member.guild.id, member.id):
            return

        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                embed = discord.Embed(
                    description=f"{member.mention} joined **{after.channel.name}**",
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
                embed.set_footer(text=f"User ID: {member.id}")
                embed.add_field(name="**Current Channel**", value=after.channel.mention, inline=False)
                await self._log(member.guild.id, "voice", embed)
            elif after.channel is None and before.channel is not None:
                embed = discord.Embed(
                    description=f"{member.mention} left **{before.channel.name}**",
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
                embed.set_footer(text=f"User ID: {member.id}")
                embed.add_field(name="**Old Channel**", value=before.channel.mention, inline=False)
                await self._log(member.guild.id, "voice", embed)
            else:
                embed = discord.Embed(
                    description=f"{member.mention} moved from **{before.channel.name}** to **{after.channel.name}**",
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
                embed.set_footer(text=f"User ID: {member.id}")
                embed.add_field(name="**Old Channel**", value=before.channel.mention, inline=False)
                embed.add_field(name="**Current Channel**", value=after.channel.mention, inline=False)
                await self._log(member.guild.id, "voice", embed)

        if before.self_mute != after.self_mute:
            action = "muted themselves" if after.self_mute else "unmuted themselves"
            embed = discord.Embed(
                description=f"{member.mention} {action}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            ch = after.channel or before.channel
            if ch:
                embed.add_field(name="**Current Channel**", value=ch.mention, inline=False)
            await self._log(member.guild.id, "voice", embed)

        if before.mute != after.mute:
            entry = await _get_audit_entry(member.guild, discord.AuditLogAction.member_update, member.id)
            mod = entry.user if entry else None
            if after.mute:
                action = f"got muted by {mod.mention}" if mod else "got server muted"
            else:
                action = f"got unmuted by {mod.mention}" if mod else "got server unmuted"
            embed = discord.Embed(
                description=f"{member.mention} {action}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            ch = after.channel or before.channel
            if ch:
                embed.add_field(name="**Current Channel**", value=ch.mention, inline=False)
            await self._log(member.guild.id, "voice", embed)

        if before.self_deaf != after.self_deaf:
            action = "deafened themselves" if after.self_deaf else "undeafened themselves"
            embed = discord.Embed(
                description=f"{member.mention} {action}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            ch = after.channel or before.channel
            if ch:
                embed.add_field(name="**Current Channel**", value=ch.mention, inline=False)
            await self._log(member.guild.id, "voice", embed)

        if before.deaf != after.deaf:
            entry = await _get_audit_entry(member.guild, discord.AuditLogAction.member_update, member.id)
            mod = entry.user if entry else None
            if after.deaf:
                action = f"got deafened by {mod.mention}" if mod else "got server deafened"
            else:
                action = f"got undeafened by {mod.mention}" if mod else "got server undeafened"
            embed = discord.Embed(
                description=f"{member.mention} {action}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            ch = after.channel or before.channel
            if ch:
                embed.add_field(name="**Current Channel**", value=ch.mention, inline=False)
            await self._log(member.guild.id, "voice", embed)

        if before.self_stream != after.self_stream:
            action = "started streaming" if after.self_stream else "stopped streaming"
            embed = discord.Embed(
                description=f"{member.mention} {action}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            ch = after.channel or before.channel
            if ch:
                embed.add_field(name="**Current Channel**", value=ch.mention, inline=False)
            await self._log(member.guild.id, "voice", embed)

        if before.suppress != after.suppress:
            action = "got suppressed" if after.suppress else "got unsuppressed"
            embed = discord.Embed(
                description=f"{member.mention} {action}",
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name="Voice State Updated", icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            ch = after.channel or before.channel
            if ch:
                embed.add_field(name="**Current Channel**", value=ch.mention, inline=False)
            await self._log(member.guild.id, "voice", embed)

    @Package.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]) -> None:
        before_map = {e.id: e for e in before}
        after_map = {e.id: e for e in after}

        for emoji in after:
            if emoji.id not in before_map:
                entry = await _get_audit_entry(guild, discord.AuditLogAction.emoji_create, emoji.id)
                embed = discord.Embed(timestamp=discord.utils.utcnow())
                if entry and entry.user:
                    embed.description = f"Emoji created by {entry.user.mention}"
                    embed.set_author(name="Emoji Created", icon_url=entry.user.display_avatar.url)
                    embed.set_footer(text=f"User ID: {entry.user.id}")
                else:
                    embed.description = "Emoji created"
                    embed.set_author(name="Emoji Created")
                embed.set_thumbnail(url=emoji.url)
                embed.add_field(name="**Name**", value=emoji.name, inline=True)
                await self._log(guild.id, "emojis", embed)

        for emoji in before:
            if emoji.id not in after_map:
                entry = await _get_audit_entry(guild, discord.AuditLogAction.emoji_delete, emoji.id)
                embed = discord.Embed(timestamp=discord.utils.utcnow())
                if entry and entry.user:
                    embed.description = f"Emoji **{emoji.name}** deleted by {entry.user.mention}"
                    embed.set_author(name="Emoji Deleted", icon_url=entry.user.display_avatar.url)
                    embed.set_footer(text=f"User ID: {entry.user.id}")
                else:
                    embed.description = f"Emoji **{emoji.name}** deleted"
                    embed.set_author(name="Emoji Deleted")
                await self._log(guild.id, "emojis", embed)

        for eid, after_emoji in after_map.items():
            before_emoji = before_map.get(eid)
            if before_emoji and before_emoji.name != after_emoji.name:
                entry = await _get_audit_entry(guild, discord.AuditLogAction.emoji_update, after_emoji.id)
                embed = discord.Embed(timestamp=discord.utils.utcnow())
                if entry and entry.user:
                    embed.description = f"Emoji updated by {entry.user.mention}"
                    embed.set_author(name="Emoji Updated", icon_url=entry.user.display_avatar.url)
                    embed.set_footer(text=f"User ID: {entry.user.id}")
                else:
                    embed.description = "Emoji updated"
                    embed.set_author(name="Emoji Updated")
                embed.set_thumbnail(url=after_emoji.url)
                embed.add_field(name="**Name**", value=f"{before_emoji.name} -> {after_emoji.name}", inline=False)
                await self._log(guild.id, "emojis", embed)

    @Package.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        embed = discord.Embed(timestamp=discord.utils.utcnow())
        if invite.inviter:
            embed.description = f"New Invite [`{invite.code}`](https://discord.gg/{invite.code}) created by {invite.inviter.mention}"
            embed.set_author(name="Invite Created", icon_url=invite.inviter.display_avatar.url)
            embed.set_footer(text=f"User ID: {invite.inviter.id}")
        else:
            embed.description = f"New Invite [`{invite.code}`](https://discord.gg/{invite.code}) created"
            embed.set_author(name="Invite Created")

        await self._log(invite.guild.id, "invites", embed)

    @Package.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        embed = discord.Embed(
            description=f"Invite [`{invite.code}`](https://discord.gg/{invite.code}) deleted",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Invite Deleted")

        await self._log(invite.guild.id, "invites", embed)

    @Package.listener("on_guild_channel_update")
    async def _channel_overwrite_logger(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        before_overwrites = dict(before.overwrites)
        after_overwrites = dict(after.overwrites)
        all_targets = set(before_overwrites.keys()) | set(after_overwrites.keys())

        for target in all_targets:
            old = before_overwrites.get(target)
            new = after_overwrites.get(target)
            if old == new:
                continue

            target_label = target.mention if hasattr(target, "mention") else str(target)
            if old is None and new is not None:
                action = discord.AuditLogAction.overwrite_create
                title = "Channel Permissions Created"
                description = f"{target_label} permissions for {after.mention} created"
            elif old is not None and new is None:
                action = discord.AuditLogAction.overwrite_delete
                title = "Channel Permissions Deleted"
                description = f"{target_label} permissions for {after.mention} deleted"
            else:
                action = discord.AuditLogAction.overwrite_update
                title = "Channel Permissions Updated"
                description = f"{target_label} permissions for {after.mention} updated"

            entry = await _get_audit_entry(after.guild, action, after.id)
            moderator = entry.user if entry else None
            if moderator:
                description += f" by {moderator.mention}"

            embed = discord.Embed(description=description, timestamp=discord.utils.utcnow())
            if moderator:
                embed.set_author(name=title, icon_url=moderator.display_avatar.url)
                embed.set_footer(text=f"User ID: {moderator.id}")
            else:
                embed.set_author(name=title)

            permission_changes = _format_overwrite_changes(old, new)
            if permission_changes:
                embed.add_field(name="**Changes**", value="\n".join(permission_changes[:25]), inline=False)

            await self._log(after.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        embed = discord.Embed(
            description=f"Thread {thread.mention} created in {thread.parent.mention if thread.parent else 'unknown'}",
            timestamp=discord.utils.utcnow(),
        )
        if thread.owner:
            embed.set_author(name="Thread Created", icon_url=thread.owner.display_avatar.url)
            embed.set_footer(text=f"User ID: {thread.owner_id}")
            embed.description = f"Thread {thread.mention} created by {thread.owner.mention}"
        else:
            embed.set_author(name="Thread Created")
        await self._log(thread.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        embed = discord.Embed(
            description=f"Thread **#{thread.name}** deleted\nThread was created at <t:{int(thread.created_at.timestamp())}:F> (<t:{int(thread.created_at.timestamp())}:R>)" if thread.created_at else f"Thread **#{thread.name}** deleted",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Thread Deleted")
        await self._log(thread.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"**Name**: {before.name} -> {after.name}")
        if before.archived != after.archived:
            changes.append(f"**Archived**: `{before.archived}` -> `{after.archived}`")
        if before.locked != after.locked:
            changes.append(f"**Locked**: `{before.locked}` -> `{after.locked}`")

        if not changes:
            return

        embed = discord.Embed(
            description=f"Thread {after.mention} updated",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="Thread Updated")
        embed.add_field(name="**Changes**", value="\n".join(changes), inline=True)
        await self._log(after.guild.id, "channels", embed)

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
                return await ctx.fail(f"Invalid event type. Valid: {', '.join(f'`{e}`' for e in EVENT_TYPES)}")
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
            return await ctx.fail(f"Invalid event type. Valid: {', '.join(f'`{e}`' for e in EVENT_TYPES)}")

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
            return await ctx.fail(f"Invalid event type. Valid: {', '.join(f'`{e}`' for e in EVENT_TYPES)}")

        hex_color = hex_color.strip("#")
        try:
            int(hex_color, 16)
        except ValueError:
            return await ctx.fail("Invalid hex color code")

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
            return await ctx.fail(f"No custom colors set for {channel.mention}")

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
            return await ctx.fail(f"{target.mention} is already **ignored** from logging")

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
            return await ctx.fail(f"{target.mention} is not **ignored**")
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
            return await ctx.fail("No members or channels are **ignored** from logging")

        lines = []
        for row in rows:
            if row[1] == "member":
                obj = ctx.guild.get_member(row[0])
            else:
                obj = ctx.guild.get_channel(row[0])
            if obj:
                lines.append(f"{obj.mention} ({row[1]})")

        if not lines:
            return await ctx.fail("No valid ignored entries found")

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
            return await ctx.fail("No logging configuration found")

        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(row[0])
            if channel:
                events_str = ", ".join(f"`{e}`" for e in row[1])
                lines.append(f"{channel.mention} — {events_str}")

        if not lines:
            return await ctx.fail("No valid logging channels found")

        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            discord.Embed(title="Logging Configuration", color=self.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )


async def setup(bot: Bleed):
    await bot.add_cog(Log(bot))
