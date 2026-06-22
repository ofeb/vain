from __future__ import annotations

import discord

from core.discord.package import Package


class LogEvents:
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

