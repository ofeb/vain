from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional, Union

import discord

from core.discord.package import Package

from core.discord.views.embed import panel_embed

def label_line(label: str, value: str) -> str:
    return f"-# **{label.lower()}**: {value}"

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




def _log_container(title: str, lines: list[str]) -> "discord.ui.LayoutView":
    """Colorless C2 log card — title, separator, history-style rows."""
    from discord import ui as _ui
    from core.discord.ctx import layout_from_items
    container = _ui.Container()
    for _attr in ("accent_color", "accent_colour"):
        if hasattr(container, _attr):
            try:
                setattr(container, _attr, None)
            except Exception:
                pass
    container.add_item(_ui.TextDisplay(f"**{title}**"))
    container.add_item(_ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
    cleaned = [ln.strip() for ln in (lines or []) if (ln or "").strip()]
    body = "\n".join(cleaned) if cleaned else "-# *no details*"
    container.add_item(_ui.TextDisplay(body))
    return layout_from_items([container], timeout=None)


def _when_line(ts=None) -> str:
    if ts is None:
        import time as _time
        ts = int(_time.time())
    else:
        ts = int(ts)
    return f"-# **when**: <t:{ts}:F> · <t:{ts}:R>"



def _components_to_container_script(message: discord.Message) -> list[str]:
    """Best-effort {container} scripts from Components V2 message items."""
    scripts: list[str] = []
    components = list(getattr(message, "components", None) or [])
    if not components:
        return scripts

    def _walk(node, acc: list[str]) -> None:
        if node is None:
            return
        
        content = getattr(node, "content", None)
        if content is None and hasattr(node, "text"):
            content = getattr(node, "text", None)
        tname = type(node).__name__
        if content and tname in ("TextDisplay", "Text"):
            acc.append(str(content))
        
        for attr in ("children", "items", "components", "accessory"):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, (list, tuple)):
                for c in child:
                    _walk(c, acc)
            else:
                _walk(child, acc)

    
    tops = components
    for top in tops:
        texts: list[str] = []
        _walk(top, texts)
        if not texts:
            continue
        parts = ["{container}"]
        for i, tx in enumerate(texts):
            if i:
                parts.append("$v{separator: true}")
            
            parts.append(f"$v{{description: {tx}}}")
        scripts.append("".join(parts))
    return scripts


def _author_label(author: discord.abc.User) -> str:
    name = getattr(author, "display_name", None) or getattr(author, "name", None) or "unknown"
    return f"@{name} ({author.id})"


def _embed_to_ce_script(embed: discord.Embed) -> str:
    """Convert a discord.Embed to a vain {embed} script for ,ce recreation."""
    parts: list[str] = ["{embed}"]
    if embed.title:
        parts.append(f"$v{{title: {embed.title}}}")
    if embed.description:
        parts.append(f"$v{{description: {embed.description}}}")
    if embed.color is not None:
        try:
            parts.append(f"$v{{color: #{int(embed.color.value):06x}}}")
        except Exception:
            pass
    if embed.url:
        parts.append(f"$v{{url: {embed.url}}}")
    if embed.timestamp:
        parts.append("$v{timestamp}")
    if embed.author and embed.author.name:
        section = f"author: {embed.author.name}"
        if embed.author.icon_url:
            section += f" && {embed.author.icon_url}"
        if embed.author.url:
            section += f" && {embed.author.url}"
        parts.append(f"$v{{{section}}}")
    if embed.footer and embed.footer.text:
        section = f"footer: {embed.footer.text}"
        if embed.footer.icon_url:
            section += f" && {embed.footer.icon_url}"
        parts.append(f"$v{{{section}}}")
    if embed.image and embed.image.url:
        parts.append(f"$v{{image: {embed.image.url}}}")
    if embed.thumbnail and embed.thumbnail.url:
        parts.append(f"$v{{thumbnail: {embed.thumbnail.url}}}")
    for field in embed.fields:
        name = field.name or "field"
        value = field.value or ""
        inline = " && true" if field.inline else ""
        parts.append(f"$v{{field: {name} && {value}{inline}}}")
    return "".join(parts)



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
        ts = int(message.created_at.timestamp())
        lines = [
            _when_line(ts),
            f"-# **author**: {message.author.mention} (`{message.author.id}`)",
            f"-# **channel**: {message.channel.mention}",
        ]
        content = (message.content or "").strip()
        if content:
            lines.append(f"-# **content**: {content[:900]}")
        elif message.attachments:
            lines.append("-# **content**: *deleted image attachment*")
        else:
            lines.append("-# **content**: *no text*")
        imgs = [
            a for a in message.attachments
            if (a.content_type or "").startswith("image")
            or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        ]
        if imgs:
            names = ", ".join(f"[`{a.filename}`]({a.url})" for a in imgs[:8])
            lines.append(f"-# **images**: {names}")
        view = _log_container("Message deleted", lines)
        await self._log(message.guild.id, "messages", view)


    @Package.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        if guild is None:
            return
        if await self._is_ignored(guild.id, channel.id):
            return

        import time as _time
        from datetime import datetime as _dt, timezone as _tz

        authors: dict[int, discord.abc.User] = {}
        ordered = sorted(
            messages,
            key=lambda m: m.created_at or discord.utils.utcnow(),
        )
        uncached = 0
        file_blocks: list[str] = []

        for msg in ordered:
            author = msg.author
            
            if author is None:
                uncached += 1
                file_blocks.append(f"[unknown] (message id {msg.id})")
                file_blocks.append("")
                continue

            authors[author.id] = author
            label = _author_label(author)
            text = (msg.content or "").strip()
            embeds = list(getattr(msg, "embeds", None) or [])
            att_urls = [a.url for a in (getattr(msg, "attachments", None) or []) if getattr(a, "url", None)]

            if text:
                file_blocks.append(f"{label}: {text}")
            else:
                file_blocks.append(f"{label}:")

            if embeds:
                for emb in embeds:
                    try:
                        script = _embed_to_ce_script(emb)
                    except Exception:
                        script = "{embed}$v{description: *could not serialize embed*}"
                    file_blocks.append(f"embed (recreate using ,ce): {script}")
            else:
                try:
                    for cscript in _components_to_container_script(msg):
                        if cscript and str(cscript).strip() not in ("", "{container}"):
                            file_blocks.append(f"container (recreate using ,cb): {cscript}")
                except Exception:
                    pass

            if att_urls:
                file_blocks.append("attachments: " + ", ".join(att_urls))

            
            stickers = list(getattr(msg, "stickers", None) or [])
            if stickers:
                names = ", ".join(getattr(s, "name", str(s)) for s in stickers)
                file_blocks.append(f"stickers: {names}")

            file_blocks.append("")

        
        now_ts = int(_time.time())
        now_dt = _dt.fromtimestamp(now_ts, tz=_tz.utc)
        time_24 = now_dt.strftime("%H:%M")
        day = now_dt.day
        if 11 <= day <= 13:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        date_str = f"{day}{suffix} of {now_dt.strftime('%B, %Y')}"

        ch_label = getattr(channel, "name", None) or str(getattr(channel, "id", "unknown"))
        ch_id = getattr(channel, "id", "unknown")
        header = [
            "vain logs",
            f"in: #{ch_label} ({ch_id})",
            f"purged @ {time_24} UTC",
            f"date: {date_str}",
            "",
            "---",
            "",
        ]
        file_text = chr(10).join(header + file_blocks).rstrip() + chr(10)
        file_content = file_text.encode("utf-8", errors="replace")

        id_list = ", ".join(f"`{uid}`" for uid in authors.keys())
        people = " ".join(a.mention for a in authors.values()) if authors else "*none resolved*"
        ch_mention = channel.mention if hasattr(channel, "mention") else f"#{ch_label}"

        lines = [
            _when_line(now_ts),
            f"-# **channel**: {ch_mention} (`{ch_id}`)",
            f"-# **count**: `{len(messages)}` messages",
        ]
        if uncached:
            lines.append(f"-# **uncached**: `{uncached}`")
        lines.append(f"-# **people**: {people}")
        if authors:
            lines.append(f"-# **ids**: {id_list}")

        view = _log_container("Multiple messages deleted", lines)
        await self._log(
            guild.id,
            "messages",
            view,
            file_content=file_content,
            file_name="multiple-deleted.txt",
        )


    @Package.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if await self._is_ignored(before.guild.id, before.channel.id):
            return
        if await self._is_ignored(before.guild.id, before.author.id):
            return
        ts = int(discord.utils.utcnow().timestamp())
        lines = [
            _when_line(ts),
            f"-# **author**: {before.author.mention} (`{before.author.id}`)",
            f"-# **channel**: {before.channel.mention}",
            f"-# **message**: [jump]({after.jump_url})",
            f"-# **before**: {(before.content or '')[:500] or '*empty*'}",
            f"-# **after**: {(after.content or '')[:500] or '*empty*'}",
        ]
        view = _log_container("Message edited", lines)
        await self._log(before.guild.id, "messages", view)


    @Package.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or payload.user_id == getattr(self.bot.user, "id", None):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if await self._is_ignored(payload.guild_id, payload.channel_id):
            return
        if await self._is_ignored(payload.guild_id, payload.user_id):
            return
        user = guild.get_member(payload.user_id) or self.bot.get_user(payload.user_id)
        if user is None or getattr(user, "bot", False):
            return
        jump = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        lines = [
            _when_line(),
            f"-# **user**: {user.mention} (`{user.id}`)",
            f"-# **emoji**: {payload.emoji}",
            f"-# **message**: [jump]({jump})",
        ]
        view = _log_container("Reaction added", lines)
        await self._log(payload.guild_id, "messages", view)

    @Package.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if await self._is_ignored(payload.guild_id, payload.channel_id):
            return
        if await self._is_ignored(payload.guild_id, payload.user_id):
            return
        user = guild.get_member(payload.user_id) or self.bot.get_user(payload.user_id)
        if user is None or getattr(user, "bot", False):
            return
        jump = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        lines = [
            _when_line(),
            f"-# **user**: {user.mention} (`{user.id}`)",
            f"-# **emoji**: {payload.emoji}",
            f"-# **message**: [jump]({jump})",
        ]
        view = _log_container("Reaction removed", lines)
        await self._log(payload.guild_id, "messages", view)


    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if await self._is_ignored(member.guild.id, member.id):
            return

        embed = panel_embed(
            author="Member joined",
            author_icon=member.display_avatar.url,
            lines=[
                f"{member.mention} joined the server",
                label_line("Account Created", f"<t:{int(member.created_at.timestamp())}:R>"),
            ],
            footer=f"User ID : {member.id}",
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
                author="Member kicked",
                author_icon=member.display_avatar.url,
                lines=lines,
                footer=f"User ID : {member.id}",
            )
            await self._log(member.guild.id, "members", embed)
            return

        lines = [f"{member.mention} left the server"]
        if member.joined_at:
            lines.append(label_line("Joined", f"<t:{int(member.joined_at.timestamp())}:R>"))
        embed = panel_embed(
            author="Member left",
            author_icon=member.display_avatar.url,
            lines=lines,
            footer=f"User ID : {member.id}",
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
                author="Nickname changed",
                author_icon=after.display_avatar.url,
                lines=[
                    f"{after.mention} nickname changed",
                    label_line("Before", before.nick or before.name),
                    label_line("After", after.nick or after.name),
                ],
                footer=f"User ID : {after.id}",
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
                    footer=f"User ID : {after.id}",
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
                    footer=f"User ID : {after.id}",
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
                author="Member roles updated",
                author_icon=after.display_avatar.url,
                lines=lines,
                footer=f"User ID : {after.id}",
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
                author="Member roles updated",
                author_icon=after.display_avatar.url,
                lines=lines,
                footer=f"User ID : {after.id}",
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
            author="Member banned",
            author_icon=user.display_avatar.url,
            lines=lines,
            footer=f"User ID : {user.id}",
        )
        await self._log(guild.id, "members", embed)

    @Package.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        lines = [f"{user.mention} was unbanned from the server"]
        entry = await _get_audit_entry(guild, discord.AuditLogAction.unban, user.id)
        if entry and entry.user:
            lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))

        embed = panel_embed(
            author="Member unbanned",
            author_icon=user.display_avatar.url,
            lines=lines,
            footer=f"User ID : {user.id}",
        )
        await self._log(guild.id, "members", embed)

    @Package.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        count = self._track_bulk_event(role.guild.id, "role_create")
        role_color = role.color.value if role.color.value else 0xE1D2DE
        if count >= self._BULK_THRESHOLD and count == self._BULK_THRESHOLD:
            lines = [f"**{count}** roles created in {role.guild.name}"]
            entry = await _get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
            footer = None
            author_icon = None
            if entry and entry.user:
                lines.append(label_line("Moderator", f"{entry.user.mention} (`{entry.user.id}`)"))
                footer = f"User ID : {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk role create",
                author="Bulk role create",
                author_icon=author_icon,
                lines=lines,
                footer=footer,
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
            author="Role created",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
                footer = f"User ID : {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk role delete",
                author="Bulk role delete",
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
            author="Role deleted",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
            author="Role updated",
            author_icon=moderator.display_avatar.url if moderator else None,
            lines=lines,
            footer=f"User ID : {moderator.id}" if moderator else None,
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
                footer = f"User ID : {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk channel create",
                author="Bulk channel create",
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
            author="Channel created",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
                footer = f"User ID : {entry.user.id}"
                author_icon = entry.user.display_avatar.url
            embed = panel_embed(
                title="Bulk channel delete",
                author="Bulk channel delete",
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
            author="Channel deleted",
            author_icon=entry.user.display_avatar.url if entry and entry.user else None,
            lines=lines,
            footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
            author="Channel updated",
            author_icon=moderator.display_avatar.url if moderator else None,
            lines=lines,
            footer=f"User ID : {moderator.id}" if moderator else None,
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
                footer=f"User ID : {member.id}",
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
                        footer=f"Channel ID : {after.channel.id}",
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
                    footer=f"User ID : {member.id}",
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
                    footer=f"User ID : {member.id}",
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
                    footer=f"User ID : {member.id}",
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
                    author="Emoji created",
                    author_icon=entry.user.display_avatar.url if entry and entry.user else None,
                    lines=lines,
                    footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
                    author="Emoji deleted",
                    author_icon=entry.user.display_avatar.url if entry and entry.user else None,
                    lines=lines,
                    footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
                    author="Emoji updated",
                    author_icon=entry.user.display_avatar.url if entry and entry.user else None,
                    lines=lines,
                    footer=f"User ID : {entry.user.id}" if entry and entry.user else None,
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
                author="Invite created",
                author_icon=invite.inviter.display_avatar.url,
                lines=[f"New Invite {invite_url} created by {invite.inviter.mention}"],
                footer=f"User ID : {invite.inviter.id}",
            )
        else:
            embed = panel_embed(
                author="Invite created",
                lines=[f"New Invite {invite_url} created"],
            )
        await self._log(invite.guild.id, "invites", embed)

    @Package.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        embed = panel_embed(
            author="Invite deleted",
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
                footer=f"User ID : {moderator.id}" if moderator else None,
            )
            await self._log(after.guild.id, "channels", embed)

    @Package.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if thread.owner:
            lines = [f"Thread {thread.mention} created by {thread.owner.mention}"]
            embed = panel_embed(
                author="Thread created",
                author_icon=thread.owner.display_avatar.url,
                lines=lines,
                footer=f"User ID : {thread.owner_id}",
            )
        else:
            embed = panel_embed(
                author="Thread created",
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
        embed = panel_embed(author="Thread deleted", lines=lines)
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
            author="Thread updated",
            lines=[
                f"Thread {after.mention} updated",
                label_line("Changes", "\n".join(changes)),
            ],
        )
        await self._log(after.guild.id, "channels", embed)

