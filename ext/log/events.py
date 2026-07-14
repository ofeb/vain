from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional, Union

import discord

from core.discord.package import Package
from core.tools.aesthetic import label_line, panel_embed


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
            changes.append(label_line(label, f"`{old_str}` → `{new_str}`"))
    return changes


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


class LogEvents:
    _BULK_THRESHOLD: int = 3
    _BULK_WINDOW: float = 10.0

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "_bulk_tracker"):
            cls._bulk_tracker: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    def _track_bulk_event(self, guild_id: int, event_key: str) -> int:
        now = time.monotonic()
        bucket = self._bulk_tracker[guild_id][event_key]
        bucket[:] = [t for t in bucket if now - t < self._BULK_WINDOW]
        bucket.append(now)
        return len(bucket)

    def _should_suppress_individual(self, guild_id: int, event_key: str) -> bool:
        now = time.monotonic()
        bucket = self._bulk_tracker[guild_id][event_key]
        bucket[:] = [t for t in bucket if now - t < self._BULK_WINDOW]
        return len(bucket) >= self._BULK_THRESHOLD

    @Package.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if await self._is_ignored(message.guild.id, message.channel.id):
            return
        if await self._is_ignored(message.guild.id, message.author.id):
            return

        lines = [
            f"Message from {message.author.mention} deleted in {message.channel.mention}",
            label_line("Sent", f"<t:{int(message.created_at.timestamp())}>"),
        ]
        if message.content:
            lines.append(label_line("Content", message.content[:1024]))
        if message.attachments:
            urls = "\n".join(a.url for a in message.attachments[:5])
            lines.append(label_line("Attachments", urls[:1024]))

        embed = panel_embed(
            author="Message Deleted",
            author_icon=message.author.display_avatar.url,
            lines=lines,
            footer=f"User ID » {message.author.id}",
        )
        await self._log(message.guild.id, "messages", embed)

    @Package.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        messages = [m for m in messages if not m.author.bot and m.guild]
        if not messages:
            return

        guild = messages[0].guild
        channel = messages[0].channel

        if await self._is_ignored(guild.id, channel.id):
            return

        uncached = sum(1 for m in messages if m.content is None)

        members: dict[int, discord.Member] = {}
        for m in messages:
            if m.author and not m.author.bot:
                members[m.author.id] = m.author

        lines: list[str] = []
        for m in messages:
            if m.content:
                ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"[{ts}] {m.author}: {m.content}")

        lines = [
            f"**{len(messages)}** messages deleted in {channel.mention}",
        ]
        if uncached:
            lines.append(
                f"({uncached} message{'s' if uncached != 1 else ''} were not cached)"
            )
        if members:
            member_list = "\n".join(
                f"{m.mention} (`{m}`) ({m.id})" for m in members.values()
            )
            lines.append(
                label_line(
                    f"{len(members)} member{'s' if len(members) != 1 else ''}",
                    member_list[:1024],
                )
            )

        embed = panel_embed(
            title="Bulk Message Delete",
            lines=lines,
            footer=f"Channel ID » {channel.id}",
        )

        file_content = "\n".join(lines).encode() if lines else None
        await self._log(
            guild.id,
            "messages",
            embed,
            file_content=file_content,
            file_name="messages.txt",
        )

    @Package.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if await self._is_ignored(before.guild.id, before.channel.id):
            return
        if await self._is_ignored(before.guild.id, before.author.id):
            return

        embed = panel_embed(
            author="Message Edited",
            author_icon=before.author.display_avatar.url,
            lines=[
                f"Message from {before.author.mention} edited <t:{int(discord.utils.utcnow().timestamp())}:R>",
                f"[View the message in #{before.channel.name}]({after.jump_url})",
                label_line("Before", before.content[:1024] or "*empty*"),
                label_line("After", after.content[:1024] or "*empty*"),
            ],
            footer=f"User ID » {before.author.id}",
        )
        await self._log(before.guild.id, "messages", embed)

    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if await self._is_ignored(member.guild.id, member.id):
            return

        embed = panel_embed(
            author="Member Joined",
            author_icon=member.display_avatar.url,
            lines=[
                f"{member.mention} joined the server",
                label_line("Account Created", f"<t:{int(member.created_at.timestamp())}:R>"),
            ],
            footer=f"User ID » {member.id}",
            thumbnail=member.display_avatar.url,
        )
        await self._log(member.guild.id, "members", embed)

    @Package.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if await self._is_ignored(member.guild.id, member.id):
            return

        entry = await _get_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if entry:
            lines = [f"{member.mention} was kicked from the server"]
            if entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
            if entry.reason:
                lines.append(label_line("Reason", entry.reason))
            embed = panel_embed(
                author="Member Kicked",
                author_icon=member.display_avatar.url,
                lines=lines,
                footer=f"User ID » {member.id}",
            )
            await self._log(member.guild.id, "members", embed)
            return

        lines = [f"{member.mention} left the server"]
        if member.joined_at:
            lines.append(label_line("Joined", f"<t:{int(member.joined_at.timestamp())}:R>"))
        embed = panel_embed(
            author="Member Left",
            author_icon=member.display_avatar.url,
            lines=lines,
            footer=f"User ID » {member.id}",
        )
        await self._log(member.guild.id, "members", embed)

    @Package.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.bot:
            return
        if await self._is_ignored(after.guild.id, after.id):
            return

        if before.nick != after.nick:
            embed = panel_embed(
                author="Nickname Changed",
                author_icon=after.display_avatar.url,
                lines=[
                    f"{after.mention} nickname changed",
                    label_line("Before", before.nick or before.name),
                    label_line("After", after.nick or after.name),
                ],
                footer=f"User ID » {after.id}",
            )
            await self._log(after.guild.id, "members", embed)

        before_timeout = getattr(before, 'timed_out_until', None)
        after_timeout = getattr(after, 'timed_out_until', None)
        if before_timeout != after_timeout:
            if after_timeout and after_timeout > discord.utils.utcnow():
                lines = [
                    f"{after.mention} timed out until <t:{int(after_timeout.timestamp())}> (<t:{int(after_timeout.timestamp())}:R>)",
                ]
                entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_update, after.id)
                if entry and entry.user:
                    lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                embed = panel_embed(
                    author="Member Timed Out",
                    author_icon=after.display_avatar.url,
                    lines=lines,
                    footer=f"User ID » {after.id}",
                )
                await self._log(after.guild.id, "members", embed)
            elif before_timeout and (
                not after_timeout
                or after_timeout <= discord.utils.utcnow()
            ):
                lines = [f"{after.mention} timeout removed early"]
                entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_update, after.id)
                if entry and entry.user:
                    lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                embed = panel_embed(
                    author="Member Timed Out",
                    author_icon=after.display_avatar.url,
                    lines=lines,
                    footer=f"User ID » {after.id}",
                )
                await self._log(after.guild.id, "members", embed)

        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)

        for role in added:
            if role.is_default():
                continue
            lines = [f"{after.mention} was granted {role.mention}"]
            entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_role_update, after.id)
            if entry and entry.user:
                if entry.user.id == after.id:
                    lines.append(label_line("Self-Assigned", f"{after.mention} (`{after.id}`)"))
                else:
                    lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
            embed = panel_embed(
                author="Member Roles Updated",
                author_icon=after.display_avatar.url,
                lines=lines,
                footer=f"User ID » {after.id}",
            )
            await self._log(after.guild.id, "roles", embed)

        for role in removed:
            if role.is_default():
                continue
            lines = [f"{after.mention} was removed from {role.mention}"]
            entry = await _get_audit_entry(after.guild, discord.AuditLogAction.member_role_update, after.id)
            if entry and entry.user:
                if entry.user.id == after.id:
                    lines.append(label_line("Self-Assigned", f"{after.mention} (`{after.id}`)"))
                else:
                    lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
            embed = panel_embed(
                author="Member Roles Updated",
                author_icon=after.display_avatar.url,
                lines=lines,
                footer=f"User ID » {after.id}",
            )
            await self._log(after.guild.id, "roles", embed)

    @Package.listener()
    async def on_member_ban(self, guild: discord.Guild, user: Union[discord.User, discord.Member]) -> None:
        if await self._is_ignored(guild.id, user.id):
            return

        lines = [f"{user.mention} was banned from the server"]
        entry = await _get_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if entry:
            if entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
            if entry.reason:
                lines.append(label_line("Reason", entry.reason))

        embed = panel_embed(
            author="Member Banned",
            author_icon=user.display_avatar.url,
            lines=lines,
            footer=f"User ID » {user.id}",
        )
        await self._log(guild.id, "members", embed)

    @Package.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        lines = [f"{user.mention} was unbanned from the server"]
        entry = await _get_audit_entry(guild, discord.AuditLogAction.unban, user.id)
        if entry and entry.user:
            lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))

        embed = panel_embed(
            author="Member Unbanned",
            author_icon=user.display_avatar.url,
            lines=lines,
            footer=f"User ID » {user.id}",
        )
        await self._log(guild.id, "members", embed)

    @Package.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        count = self._track_bulk_event(role.guild.id, "role_create")
        role_color = role.color.value if role.color.value else 0xD4B8D0
        if count >= self._BULK_THRESHOLD and count == self._BULK_THRESHOLD:
            lines = [f"**{count}** roles created in {role.guild.name}"]
            entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
            footer = None
            author_icon = None
            if entry and entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                footer = f"User ID » {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk Role Create",
                author="Bulk Role Create",
                author_icon=author_icon,
                lines=lines,
                footer=footer,
                color=role_color,
            )
            await self._log(role.guild.id, "roles", embed)
            return

        if self._should_suppress_individual(role.guild.id, "role_create"):
            return

        entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        lines = [
            f"Role {role.mention} created by {entry.user.mention}"
            if entry and entry.user
            else f"Role {role.mention} created",
            label_line("Name", role.name),
            label_line("Color", f"`#{role.color.value:06x}`"),
        ]
        embed = panel_embed(
            author="Role Created",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
            color=role_color,
        )
        await self._log(role.guild.id, "roles", embed)

    @Package.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        count = self._track_bulk_event(role.guild.id, "role_delete")
        if count >= self._BULK_THRESHOLD and count == self._BULK_THRESHOLD:
            lines = [f"**{count}** roles deleted in {role.guild.name}"]
            entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
            footer = None
            author_icon = None
            if entry and entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                footer = f"User ID » {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk Role Delete",
                author="Bulk Role Delete",
                author_icon=author_icon,
                lines=lines,
                footer=footer,
            )
            await self._log(role.guild.id, "roles", embed)
            return

        if self._should_suppress_individual(role.guild.id, "role_delete"):
            return

        entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        lines = [
            f"Role **{role.name}** deleted by {entry.user.mention}"
            if entry and entry.user
            else f"Role **{role.name}** deleted",
            label_line(
                "Created",
                f"<t:{int(role.created_at.timestamp())}:F> (<t:{int(role.created_at.timestamp())}:R>)",
            ),
        ]
        embed = panel_embed(
            author="Role Deleted",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
        )
        await self._log(role.guild.id, "roles", embed)

    @Package.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        changes = []

        entry = await _get_audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        moderator = entry.user if entry else None

        if before.name != after.name:
            changes.append(label_line("Name", f"{before.name} → {after.name}"))

        if before.color != after.color:
            changes.append(
                label_line("Color", f"`#{before.color.value:06x}` → `#{after.color.value:06x}`")
            )

        if before.hoist != after.hoist:
            changes.append(label_line("Hoisted", f"`{before.hoist}` → `{after.hoist}`"))

        if before.mentionable != after.mentionable:
            changes.append(
                label_line("Mentionable", f"`{before.mentionable}` → `{after.mentionable}`")
            )

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
                changes.append(label_line("Permissions Updated", "\n".join(perm_changes)))

        if not changes:
            return

        lines = [
            f"Role {after.mention} updated" + (f" by {moderator.mention}" if moderator else ""),
            *changes,
        ]
        embed = panel_embed(
            author="Role Updated",
            author_icon=moderator.display_avatar.url if moderator else None,
            lines=lines,
            footer=f"User ID » {moderator.id}" if moderator else None,
        )
        await self._log(after.guild.id, "roles", embed)

    @Package.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        label = _channel_type_label(channel)

        count = self._track_bulk_event(channel.guild.id, "channel_create")
        if count >= self._BULK_THRESHOLD and count == self._BULK_THRESHOLD:
            lines = [f"**{count}** channels created in <#{channel.guild.id}>"]
            entry = await _get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
            footer = None
            author_icon = None
            if entry and entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                footer = f"User ID » {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk Channel Create",
                author="Bulk Channel Create",
                author_icon=author_icon,
                lines=lines,
                footer=footer,
            )
            await self._log(channel.guild.id, "channels", embed)
            return

        if self._should_suppress_individual(channel.guild.id, "channel_create"):
            return

        entry = await _get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        lines = [
            f"{label} {channel.mention} created by {entry.user.mention}"
            if entry and entry.user
            else f"{label} {channel.mention} created",
        ]
        embed = panel_embed(
            author="Channel Created",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
        )
        await self._log(channel.guild.id, "channels", embed)

    @Package.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        label = _channel_type_label(channel)

        count = self._track_bulk_event(channel.guild.id, "channel_delete")
        if count >= self._BULK_THRESHOLD and count == self._BULK_THRESHOLD:
            lines = [f"**{count}** channels deleted in <#{channel.guild.id}>"]
            entry = await _get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
            footer = None
            author_icon = None
            if entry and entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                footer = f"User ID » {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk Channel Delete",
                author="Bulk Channel Delete",
                author_icon=author_icon,
                lines=lines,
                footer=footer,
            )
            await self._log(channel.guild.id, "channels", embed)
            return

        if self._should_suppress_individual(channel.guild.id, "channel_delete"):
            return

        entry = await _get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        created_line = label_line(
            "Created",
            f"<t:{int(channel.created_at.timestamp())}:F> (<t:{int(channel.created_at.timestamp())}:R>)",
        )
        lines = [
            f"{label} **#{channel.name}** deleted by {entry.user.mention}"
            if entry and entry.user
            else f"{label} **#{channel.name}** deleted",
            created_line,
        ]
        embed = panel_embed(
            author="Channel Deleted",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
        )
        await self._log(channel.guild.id, "channels", embed)

    @Package.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        changes = []
        label = _channel_type_label(after)

        if before.name != after.name:
            changes.append(label_line("Name", f"{before.name} → {after.name}"))

        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                old_topic = before.topic or "No topic"
                new_topic = after.topic or "No topic"
                changes.append(label_line("Topic", f"{old_topic} → {new_topic}"))
            if before.slowmode_delay != after.slowmode_delay:
                old_slow = f"{before.slowmode_delay}s" if before.slowmode_delay else "0"
                new_slow = f"{after.slowmode_delay}s" if after.slowmode_delay else "0"
                changes.append(label_line("Slowmode Delay", f"`{old_slow}` → `{new_slow}`"))
            if before.is_nsfw() != after.is_nsfw():
                changes.append(label_line("NSFW", f"`{before.is_nsfw()}` → `{after.is_nsfw()}`"))

        if isinstance(before, discord.VoiceChannel) and isinstance(after, discord.VoiceChannel):
            if before.bitrate != after.bitrate:
                changes.append(
                    label_line(
                        "Bitrate",
                        f"`{before.bitrate / 1000:.1f}kbps` → `{after.bitrate / 1000:.1f}kbps`",
                    )
                )
            if before.user_limit != after.user_limit:
                changes.append(
                    label_line("User Limit", f"`{before.user_limit}` → `{after.user_limit}`")
                )

        if isinstance(before, discord.ForumChannel) and isinstance(after, discord.ForumChannel):
            old_tags = {t.name for t in before.available_tags}
            new_tags = {t.name for t in after.available_tags}
            added_tags = new_tags - old_tags
            removed_tags = old_tags - new_tags
            if added_tags:
                changes.append(label_line("Tags Added", ", ".join(added_tags)))
            if removed_tags:
                changes.append(label_line("Tags Removed", ", ".join(removed_tags)))

        if not changes:
            return

        entry = await _get_audit_entry(after.guild, discord.AuditLogAction.channel_update, after.id)
        moderator = entry.user if entry else None

        lines = [
            f"{label} {after.mention} updated" + (f" by {moderator.mention}" if moderator else ""),
            label_line("Changes", "\n".join(changes)),
        ]
        embed = panel_embed(
            author="Channel Updated",
            author_icon=moderator.display_avatar.url if moderator else None,
            lines=lines,
            footer=f"User ID » {moderator.id}" if moderator else None,
        )
        await self._log(after.guild.id, "channels", embed)

    @Package.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        if await self._is_ignored(member.guild.id, member.id):
            return

        def _voice_embed(headline: str, *, extra_lines: list[str] | None = None) -> discord.Embed:
            lines = [headline, *(extra_lines or [])]
            ch = after.channel or before.channel
            if ch:
                lines.append(label_line("Current Channel", ch.mention))
            return panel_embed(
                author="Voice State Updated",
                author_icon=member.display_avatar.url,
                lines=lines,
                footer=f"User ID » {member.id}",
            )

        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                join_key = f"voice_join_{after.channel.id}"
                count = self._track_bulk_event(member.guild.id, join_key)
                if count >= self._BULK_THRESHOLD and count == self._BULK_THRESHOLD:
                    embed = panel_embed(
                        title="Bulk Voice Join",
                        author="Bulk Voice Join",
                        lines=[f"**{count}** members joined {after.channel.mention}"],
                        footer=f"Channel ID » {after.channel.id}",
                    )
                    await self._log(member.guild.id, "voice", embed)
                    return
                if self._should_suppress_individual(member.guild.id, join_key):
                    return

                embed = panel_embed(
                    author="Voice State Updated",
                    author_icon=member.display_avatar.url,
                    lines=[
                        f"{member.mention} joined **{after.channel.name}**",
                        label_line("Current Channel", after.channel.mention),
                    ],
                    footer=f"User ID » {member.id}",
                )
                await self._log(member.guild.id, "voice", embed)
            elif after.channel is None and before.channel is not None:
                embed = panel_embed(
                    author="Voice State Updated",
                    author_icon=member.display_avatar.url,
                    lines=[
                        f"{member.mention} left **{before.channel.name}**",
                        label_line("Old Channel", before.channel.mention),
                    ],
                    footer=f"User ID » {member.id}",
                )
                await self._log(member.guild.id, "voice", embed)
            else:
                embed = panel_embed(
                    author="Voice State Updated",
                    author_icon=member.display_avatar.url,
                    lines=[
                        f"{member.mention} moved from **{before.channel.name}** to **{after.channel.name}**",
                        label_line("Old Channel", before.channel.mention),
                        label_line("Current Channel", after.channel.mention),
                    ],
                    footer=f"User ID » {member.id}",
                )
                await self._log(member.guild.id, "voice", embed)

        if before.self_mute != after.self_mute:
            action = "muted themselves" if after.self_mute else "unmuted themselves"
            await self._log(member.guild.id, "voice", _voice_embed(f"{member.mention} {action}"))

        if before.mute != after.mute:
            entry = await _get_audit_entry(member.guild, discord.AuditLogAction.member_update, member.id)
            mod = entry.user if entry else None
            if after.mute:
                action = f"got muted by {mod.mention}" if mod else "got server muted"
            else:
                action = f"got unmuted by {mod.mention}" if mod else "got server unmuted"
            await self._log(member.guild.id, "voice", _voice_embed(f"{member.mention} {action}"))

        if before.self_deaf != after.self_deaf:
            action = "deafened themselves" if after.self_deaf else "undeafened themselves"
            await self._log(member.guild.id, "voice", _voice_embed(f"{member.mention} {action}"))

        if before.deaf != after.deaf:
            entry = await _get_audit_entry(member.guild, discord.AuditLogAction.member_update, member.id)
            mod = entry.user if entry else None
            if after.deaf:
                action = f"got deafened by {mod.mention}" if mod else "got server deafened"
            else:
                action = f"got undeafened by {mod.mention}" if mod else "got server undeafened"
            await self._log(member.guild.id, "voice", _voice_embed(f"{member.mention} {action}"))

        if before.self_stream != after.self_stream:
            action = "started streaming" if after.self_stream else "stopped streaming"
            await self._log(member.guild.id, "voice", _voice_embed(f"{member.mention} {action}"))

        if before.suppress != after.suppress:
            action = "got suppressed" if after.suppress else "got unsuppressed"
            await self._log(member.guild.id, "voice", _voice_embed(f"{member.mention} {action}"))

    @Package.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]) -> None:
        before_map = {e.id: e for e in before}
        after_map = {e.id: e for e in after}

        for emoji in after:
            if emoji.id not in before_map:
                entry = await _get_audit_entry(guild, discord.AuditLogAction.emoji_create, emoji.id)
                lines = [
                    f"Emoji created by {entry.user.mention}"
                    if entry and entry.user
                    else "Emoji created",
                    label_line("Name", emoji.name),
                ]
                embed = panel_embed(
                    author="Emoji Created",
                    author_icon=entry.user.display_avatar.url if entry and entry.user else None,
                    lines=lines,
                    footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
                    thumbnail=emoji.url,
                )
                await self._log(guild.id, "emojis", embed)

        for emoji in before:
            if emoji.id not in after_map:
                entry = await _get_audit_entry(guild, discord.AuditLogAction.emoji_delete, emoji.id)
                lines = [
                    f"Emoji **{emoji.name}** deleted by {entry.user.mention}"
                    if entry and entry.user
                    else f"Emoji **{emoji.name}** deleted",
                ]
                embed = panel_embed(
                    author="Emoji Deleted",
                    author_icon=entry.user.display_avatar.url if entry and entry.user else None,
                    lines=lines,
                    footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
                )
                await self._log(guild.id, "emojis", embed)

        for eid, after_emoji in after_map.items():
            before_emoji = before_map.get(eid)
            if before_emoji and before_emoji.name != after_emoji.name:
                entry = await _get_audit_entry(guild, discord.AuditLogAction.emoji_update, after_emoji.id)
                lines = [
                    f"Emoji updated by {entry.user.mention}"
                    if entry and entry.user
                    else "Emoji updated",
                    label_line("Name", f"{before_emoji.name} → {after_emoji.name}"),
                ]
                embed = panel_embed(
                    author="Emoji Updated",
                    author_icon=entry.user.display_avatar.url if entry and entry.user else None,
                    lines=lines,
                    footer=f"User ID » {entry.user.id}" if entry and entry.user else None,
                    thumbnail=after_emoji.url,
                )
                await self._log(guild.id, "emojis", embed)

    @Package.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        invite_url = f"[`{invite.code}`](https://discord.gg/{invite.code})"
        if invite.inviter:
            embed = panel_embed(
                author="Invite Created",
                author_icon=invite.inviter.display_avatar.url,
                lines=[f"New Invite {invite_url} created by {invite.inviter.mention}"],
                footer=f"User ID » {invite.inviter.id}",
            )
        else:
            embed = panel_embed(
                author="Invite Created",
                lines=[f"New Invite {invite_url} created"],
            )
        await self._log(invite.guild.id, "invites", embed)

    @Package.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        embed = panel_embed(
            author="Invite Deleted",
            lines=[f"Invite [`{invite.code}`](https://discord.gg/{invite.code}) deleted"],
        )
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

            lines = [description]
            permission_changes = _format_overwrite_changes(old, new)
            if permission_changes:
                lines.append(label_line("Changes", "\n".join(permission_changes[:25])))
            embed = panel_embed(
                author=title,
                author_icon=moderator.display_avatar.url if moderator else None,
                lines=lines,
                footer=f"User ID » {moderator.id}" if moderator else None,
            )
            await self._log(after.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if thread.owner:
            lines = [f"Thread {thread.mention} created by {thread.owner.mention}"]
            embed = panel_embed(
                author="Thread Created",
                author_icon=thread.owner.display_avatar.url,
                lines=lines,
                footer=f"User ID » {thread.owner_id}",
            )
        else:
            embed = panel_embed(
                author="Thread Created",
                lines=[
                    f"Thread {thread.mention} created in {thread.parent.mention if thread.parent else 'unknown'}",
                ],
            )
        await self._log(thread.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        lines = [f"Thread **#{thread.name}** deleted"]
        if thread.created_at:
            lines.append(
                label_line(
                    "Created",
                    f"<t:{int(thread.created_at.timestamp())}:F> (<t:{int(thread.created_at.timestamp())}:R>)",
                )
            )
        embed = panel_embed(author="Thread Deleted", lines=lines)
        await self._log(thread.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        changes = []
        if before.name != after.name:
            changes.append(label_line("Name", f"{before.name} → {after.name}"))
        if before.archived != after.archived:
            changes.append(label_line("Archived", f"`{before.archived}` → `{after.archived}`"))
        if before.locked != after.locked:
            changes.append(label_line("Locked", f"`{before.locked}` → `{after.locked}`"))

        if not changes:
            return

        embed = panel_embed(
            author="Thread Updated",
            lines=[
                f"Thread {after.mention} updated",
                label_line("Changes", "\n".join(changes)),
            ],
        )
        await self._log(after.guild.id, "channels", embed)

