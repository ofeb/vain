from __future__ import annotations

import contextlib
import discord
from datetime import timedelta
from discord.ext import tasks
from discord.ext.commands import command, group
from discord.ext.commands import CommandError

from core.discord.package import Package


from core.managers.permissions import has_permissions
class ModerationCommands(Package):
    """standalone moderation commands"""

    async def cog_load(self) -> None:
        if self.db.pool is not None:
            self.tempban_watcher.start()

    async def cog_unload(self) -> None:
        if self.tempban_watcher.is_running():
            self.tempban_watcher.cancel()

    def _audit_reason(self, ctx, reason: str | None) -> str:
        base = reason or "no reason provided"
        return f"{base} | executed by {ctx.author} ({ctx.author.id})"

    def _default_reason(self, reason: str | None) -> str:
        return reason or "no reason provided"

    def _coerce_delete_days(self, value, *, default: int = 0) -> int:
        if value in (None, ""):
            return default
        raw = str(value).strip().lower()
        units = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "d": 1, "w": 7}
        if raw and raw[-1] in units and raw[:-1].isdigit():
            days = int(raw[:-1]) * units[raw[-1]]
        else:
            try:
                days = int(raw)
            except (TypeError, ValueError):
                days = default
        return max(0, min(int(days), 7))

    def _parse_duration_seconds(self, value: str | None) -> int | None:
        if not value:
            return None
        raw = str(value).strip().lower()
        if raw.isdigit():
            return int(raw)
        units = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }
        if len(raw) < 2 or raw[-1] not in units or not raw[:-1].isdigit():
            return None
        return int(raw[:-1]) * units[raw[-1]]

    def _format_duration(self, seconds: int) -> str:
        units = (
            ("week", 604800),
            ("day", 86400),
            ("hour", 3600),
            ("minute", 60),
            ("second", 1),
        )
        parts: list[str] = []
        remainder = max(0, int(seconds))
        for label, chunk in units:
            if remainder < chunk:
                continue
            count, remainder = divmod(remainder, chunk)
            parts.append(f"{count} {label}{'' if count == 1 else 's'}")
            if len(parts) == 2:
                break
        return ", ".join(parts) if parts else "0 seconds"

    def _ensure_targetable(self, ctx, member: discord.Member) -> None:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")
        if member.id == ctx.author.id:
            raise CommandError("you cannot moderate yourself")
        if member.id == ctx.guild.owner_id:
            raise CommandError("you cannot moderate the server owner")

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        bot_member = ctx.guild.me or ctx.guild.get_member(self.bot.user.id if self.bot.user else 0)
        if author and ctx.guild.owner_id != author.id and member.top_role >= author.top_role:
            raise CommandError(
                f"**{member.display_name}** has a higher or equal role than you — "
                f"their top role ({member.top_role.mention}) must be below yours ({author.top_role.mention})"
            )
        if bot_member is None:
            raise CommandError("I could not resolve my server member")
        if member.top_role >= bot_member.top_role:
            raise CommandError(
                f"**{member.display_name}** has a higher or equal role than me — "
                f"their top role ({member.top_role.mention}) must be below my highest role ({bot_member.top_role.mention})"
            )

    async def _create_case(
        self,
        ctx,
        *,
        action: str,
        target_id: int,
        reason: str | None,
    ) -> int | None:
        if getattr(self.db, "pool", None) is None:
            return None
        return await self.db.create_case(
            guild_id=ctx.guild.id,
            action=action,
            target_id=target_id,
            moderator_id=ctx.author.id,
            reason=self._default_reason(reason),
        )

    async def _send_modlog(
        self,
        ctx,
        *,
        action: str,
        target: discord.abc.User | None,
        case_id: int | None,
        reason: str | None,
    ) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        channel_id = await self.db.get_modlog_channel(ctx.guild.id)
        if not channel_id:
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        target_label = str(target) if target else "Unknown User"
        embed = discord.Embed(
            color=self.color,
            title=f"Case #{case_id}" if case_id is not None else "Moderation action",
            description=(
                f"**Action:** {action}\n"
                f"**Target:** {target_label}\n"
                f"**Moderator:** {ctx.author}\n"
                f"**Reason:** {self._default_reason(reason)}"
            ),
        )
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    def _dispatch_antinuke_action(
        self,
        ctx,
        *,
        action: str,
        case_id: int | None,
        meta: dict | None = None,
    ) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        ctx.bot.dispatch(
            "antinuke_action",
            ctx.guild,
            ctx.author,
            action,
            case_id or 0,
            meta,
        )

    @command(
        name="tempban",
        description="No description given",
    )
    @has_permissions(ban_members=True)
    async def tempban(
        self,
        ctx,
        member: discord.Member,
        duration: str,
        *,
        reason: str = None,
    ):
        """temporarily ban a member"""
        self._ensure_targetable(ctx, member)

        seconds = self._parse_duration_seconds(duration)
        if not seconds or seconds < 1:
            raise CommandError("duration must look like `30m`, `2h`, `7d`, or `1w`")

        target_display = str(member)
        target_id = member.id
        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        unban_at = discord.utils.utcnow() + timedelta(seconds=seconds)

        await member.ban(
            delete_message_seconds=0,
            reason=self._audit_reason(ctx, reason),
        )
        case_id = await self._create_case(
            ctx,
            action="tempban",
            target_id=target_id,
            reason=reason,
        )
        await self.db.add_tempban(
            ctx.guild.id,
            target_id,
            unban_at,
            ctx.author.id,
            self._default_reason(reason),
            case_id,
        )
        await self._send_modlog(
            ctx,
            action="tempban",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx,
            action="tempban",
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        return await ctx.success(
            f"Tempbanned **{target_display}** for **{self._format_duration(seconds)}** - {self._default_reason(reason)}"
        )

    @command(
        name="warn",
        description="Warns the mentioned user and private messages them the warning",
    )
    @has_permissions(manage_messages=True)
    async def warn(self, ctx, member, *, reason=None):
        """warn a member"""
        pass

    @command(
        name="moveall",
        description="Move all members in your voice channel to another channel",
    )
    @has_permissions(move_members=True)
    async def moveall(self, ctx, channel: discord.VoiceChannel):
        """move all members to another channel"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.warn("You must be in a **voice channel** to use this command")

        source = ctx.author.voice.channel

        if source.id == channel.id:
            return await ctx.warn("Source and destination **cannot** be the same")

        if not ctx.guild.me.guild_permissions.move_members:
            return await ctx.warn("I **don't** have the **Move Members** permission")

        moved = 0
        failed = 0

        for member in list(source.members):
            try:
                await member.move_to(channel, reason=f"Moveall by {ctx.author}")
                moved += 1
            except (discord.HTTPException, discord.Forbidden):
                failed += 1

        msg = f"Moved **{moved}** members from {source.mention} to {channel.mention}"
        if failed:
            msg += f" ({failed} failed)"

        return await ctx.success(msg)

    @command(
        name="stripstaff",
        description="Remove all staff roles from a member",
    )
    @has_permissions(manage_roles=True)
    async def stripstaff(self, ctx, *, member: discord.Member):
        """strip staff roles from member"""
        if member.id == ctx.author.id:
            return await ctx.warn("You cannot **strip yourself** of staff roles")

        if member.id == ctx.guild.owner_id:
            return await ctx.warn("You cannot strip the **server owner**")

        if ctx.author.top_role <= member.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.warn("Your top role must be **higher** than this member's top role")

        rows = await self.db.fetch(
            """SELECT role_id FROM staff_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )

        if not rows:
            return await ctx.warn("No **staff roles** are configured for this server")

        staff_role_ids = {row[0] for row in rows}
        removed = []

        for role in list(member.roles):
            if role.id in staff_role_ids and role < ctx.author.top_role:
                try:
                    await member.remove_roles(role, reason=f"Stripstaff by {ctx.author}")
                    removed.append(role.mention)
                except discord.HTTPException:
                    continue

        if not removed:
            return await ctx.warn(f"{member.mention} has **no dangerous roles** to strip")

        return await ctx.success(f"Stripped **{len(removed)}** dangerous roles from {member.mention}: {', '.join(removed)}")

    @command(
        name="jail",
        description="Jails the mentioned user",
    )
    @has_permissions(manage_messages=True)
    async def jail(self, ctx, member, *, reason=None):
        """jail a member"""
        pass

    @command(
        name="unjail",
        description="Unjails the mentioned user",
    )
    async def unjail(self, ctx, member, *, reason):
        """unjail a member"""
        pass

    @command(
        name="modstats",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def modstats(self, ctx, member):
        """view moderation stats for a member"""
        pass

    @command(
        name="warnings",
        description="View warnings for a member",
    )
    @has_permissions(manage_messages=True)
    async def warnings(self, ctx, member):
        """view warnings for a member"""
        pass

    @command(
        name="moderationhistory",
        description="View moderation actions from a staff member",
    )
    @has_permissions(manage_messages=True)
    async def moderationhistory(self, ctx, member, command):
        """view moderation history for a staff member"""
        pass

    @command(
        name="jaillist",
        description="View a list of every current jailed member",
    )
    @has_permissions(manage_messages=True)
    async def jaillist(self, ctx):
        """list all jailed members"""
        pass

    @command(
        name="caselog",
        description="View a case log",
    )
    @has_permissions(manage_messages=True)
    async def caselog(self, ctx, case_id):
        """view case log"""
        pass

    @group(
        name="timeout",
        description="Mutes the provided member using Discords timeout feature",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True)
    async def timeout(self, ctx, member, duration, *, reason=None):
        """timeout a member"""
        pass

    @timeout.command(
        name="list",
        description="View list of timed out members",
    )
    @has_permissions(moderate_members=True)
    async def timeout_list(self, ctx):
        """list timed out members"""
        pass

    @command(
        name="untimeout",
        description="Removes a timeout for a member",
    )
    @has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member, *, reason=None):
        """remove timeout from a member"""
        pass

    async def _mute_member(
        self,
        ctx,
        member: discord.Member,
        mute_type: str,
        *,
        duration: str | None = None,
        reason: str | None = None,
    ):
        self._ensure_targetable(ctx, member)

        role_key = f"{mute_type}muted_role_id"
        if mute_type == "":
            role_key = "muted_role_id"
        row = await self.bot.db.fetchrow(
            f"SELECT {role_key} FROM server_settings WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not row or not row.get(role_key):
            setting_name = {"": "muted", "i": "imuted", "r": "rmuted"}.get(mute_type, mute_type)
            return await ctx.warn(
                f"No **{setting_name}** role is set. "
                f"Use `{ctx.clean_prefix}settings {setting_name}` first."
            )
        role = ctx.guild.get_role(row[role_key])
        if not role:
            return await ctx.warn("The configured mute role no longer exists.")

        role_label = {"": "text-muted", "i": "image-muted", "r": "reaction-muted"}.get(mute_type, mute_type)

        expires_at = None
        if duration:
            seconds = self._parse_duration_seconds(duration)
            if not seconds:
                return await ctx.warn(f"Invalid duration `{duration}`. Examples: `30m`, `2h`, `7d`.")
            expires_at = discord.utils.utcnow() + timedelta(seconds=seconds)

        if role in member.roles:
            return await ctx.warn(f"**{member}** is already {role_label}.")

        await member.add_roles(role, reason=self._audit_reason(ctx, reason))
        await self.bot.db.execute(
            """INSERT INTO mutes (guild_id, user_id, moderator_id, mute_type, role_id, expires_at, reason)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (guild_id, user_id) DO UPDATE
               SET mute_type = $4, role_id = $5, expires_at = $6, reason = $7, moderator_id = $3""",
            ctx.guild.id, member.id, ctx.author.id, mute_type or "text",
            role.id, expires_at, self._default_reason(reason),
        )

        case_id = await self._create_case(
            ctx, action=role_label, target_id=member.id, reason=reason,
        )
        await self._send_modlog(
            ctx, action=role_label, target=member, case_id=case_id, reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx, action=role_label, case_id=case_id,
            meta={"target_id": member.id, "target_display": str(member)},
        )

        parts = [f"{role_label.title()} **{member}**"]
        if expires_at:
            parts.append(f"for **{self._format_duration(seconds)}**")
        parts.append(f"- {self._default_reason(reason)}")
        return await ctx.success(" ".join(parts))

    async def _unmute_member(
        self,
        ctx,
        member: discord.Member,
        mute_type: str,
        *,
        reason: str | None = None,
    ):
        role_key = f"{mute_type}muted_role_id"
        if mute_type == "":
            role_key = "muted_role_id"
        row = await self.bot.db.fetchrow(
            f"SELECT {role_key} FROM server_settings WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not row or not row.get(role_key):
            return await ctx.warn("No mute role is configured.")

        role = ctx.guild.get_role(row[role_key])
        if role and role in member.roles:
            await member.remove_roles(role, reason=self._audit_reason(ctx, reason))

        await self.bot.db.execute(
            "DELETE FROM mutes WHERE guild_id = $1 AND user_id = $2 AND mute_type = $3",
            ctx.guild.id, member.id, mute_type or "text",
        )

        role_label = {"": "text-muted", "i": "image-muted", "r": "reaction-muted"}.get(mute_type, mute_type)
        return await ctx.success(f"Un{mute_type if mute_type else 'mute'}d **{member}** - {self._default_reason(reason)}")

    @command(
        name="mute",
        description="Mute a member",
    )
    @has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, duration: str = None, *, reason: str = None):
        """mute a member"""
        await self._mute_member(ctx, member, "", duration=duration, reason=reason)

    @command(
        name="unmute",
        description="Unmute a member",
    )
    @has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member, *, reason: str = None):
        """unmute a member"""
        await self._unmute_member(ctx, member, "", reason=reason)

    @command(
        name="imute",
        description="Image mute a member",
    )
    @has_permissions(moderate_members=True)
    async def imute(self, ctx, member: discord.Member, *, reason: str = None):
        """image mute a member"""
        await self._mute_member(ctx, member, "i", reason=reason)

    @command(
        name="iunmute",
        description="Un-image mute a member",
    )
    @has_permissions(moderate_members=True)
    async def iunmute(self, ctx, member: discord.Member, *, reason: str = None):
        """un image mute a member"""
        await self._unmute_member(ctx, member, "i", reason=reason)

    @command(
        name="rmute",
        description="Reaction mute a member",
    )
    @has_permissions(moderate_members=True)
    async def rmute(self, ctx, member: discord.Member, *, reason: str = None):
        """reaction mute a member"""
        await self._mute_member(ctx, member, "r", reason=reason)

    @command(
        name="runmute",
        description="Un-reaction mute a member",
    )
    @has_permissions(moderate_members=True)
    async def runmute(self, ctx, member: discord.Member, *, reason: str = None):
        """un reaction mute a member"""
        await self._unmute_member(ctx, member, "r", reason=reason)

    @command(
        name="hardban",
        description="Keep a member banned",
    )
    async def hardban(self, ctx, member, *, reason=None):
        """hardban a member"""
        pass

    @command(
        name="hardban list",
        description="View list of hardbanned members",
    )
    @has_permissions(administrator=True)
    async def hardban_list(self, ctx):
        """list hardbanned members"""
        pass

    @command(
        name="clearinvites",
        description="Remove all existing invites in guild",
    )
    @has_permissions(manage_guild=True)
    async def clearinvites(self, ctx, params):
        """clear all invites"""
        pass

    @command(
        name="drag",
        description="Drag member(s) to the specified Voice Channel",
    )
    @has_permissions(move_members=True)
    async def drag(self, ctx, members, channel):
        """drag members to voice channel"""
        pass

    @command(
        name="unbanall",
        description="Unbans every member in a guild",
    )
    @has_permissions(ban_members=True)
    async def unbanall(self, ctx):
        """unban all members"""
        pass

    @command(
        name="unbanall cancel",
        description="Cancels a unban all task running",
    )
    @has_permissions(ban_members=True)
    async def unbanall_cancel(self, ctx):
        """cancel unban all task"""
        pass

    @command(
        name="unban",
        description="Unbans the mentioned user",
    )
    @has_permissions(ban_members=True)
    async def unban(self, ctx, user, *, reason=None):
        """unban a user"""
        pass

    @command(
        name="softban",
        description="Softbans the mentioned user and deleting 1 day of messages",
    )
    @has_permissions(ban_members=True)
    async def softban(
        self,
        ctx,
        member: discord.Member,
        delete_history: str = "1d",
        *,
        reason: str = None,
    ):
        """softban a member"""
        self._ensure_targetable(ctx, member)

        delete_days = self._coerce_delete_days(delete_history, default=1)
        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        target_display = str(member)
        target_id = member.id

        await member.ban(
            delete_message_seconds=delete_days * 86400,
            reason=self._audit_reason(ctx, reason),
        )
        await ctx.guild.unban(
            discord.Object(id=target_id),
            reason=self._audit_reason(ctx, "softban removal"),
        )

        case_id = await self._create_case(
            ctx,
            action="softban",
            target_id=target_id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="softban",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx,
            action="softban",
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        return await ctx.success(
            f"Softbanned **{target_display}** - {self._default_reason(reason)}"
        )

    @command(
        name="ban",
        usage="(user) (delete history) <reason>",
        example="jonathan 1d Threatening members",
        description="Bans the mentioned user",
    )
    @has_permissions(ban_members=True)
    async def ban(
        self,
        ctx,
        member: discord.Member,
        delete_history: str = "0",
        *,
        reason: str = None,
    ):
        """Bans the mentioned user"""
        self._ensure_targetable(ctx, member)

        delete_days = self._coerce_delete_days(delete_history, default=0)
        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        target_display = str(member)
        target_id = member.id

        await member.ban(
            delete_message_seconds=delete_days * 86400,
            reason=self._audit_reason(ctx, reason),
        )

        case_id = await self._create_case(
            ctx,
            action="ban",
            target_id=target_id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="ban",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx,
            action="ban",
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        return await ctx.success(
            f"Banned **{target_display}** - {self._default_reason(reason)}"
        )

    @command(
        name="kick",
        description="Kick the mentioned user",
    )
    @has_permissions(kick_members=True)
    async def kick(
        self,
        ctx,
        member: discord.Member,
        *,
        reason: str = None,
    ):
        """kick a member"""
        self._ensure_targetable(ctx, member)

        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        target_display = str(member)
        target_id = member.id

        await member.kick(reason=self._audit_reason(ctx, reason))

        case_id = await self._create_case(
            ctx,
            action="kick",
            target_id=target_id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="kick",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx,
            action="kick",
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        return await ctx.success(
            f"Kicked **{target_display}** - {self._default_reason(reason)}"
        )

    @tasks.loop(seconds=30)
    async def tempban_watcher(self) -> None:
        for entry in await self.db.fetch_due_tempbans():
            guild = self.bot.get_guild(int(entry["guild_id"]))
            if guild is None:
                continue
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await guild.unban(
                    discord.Object(id=int(entry["user_id"])),
                    reason="tempban expired",
                )
            await self.db.remove_tempban(int(entry["guild_id"]), int(entry["user_id"]))

    @command(
        name="ban recent",
        usage="(amount) <reason>",
        example="50 Threatening members",
        description="Bans the most recently joined members",
    )
    @has_permissions(ban_members=True)
    async def ban_recent(self, ctx):
        """Bans the most recently joined members"""
        pass

    @command(
        name="ban purge",
        usage="(delete history)",
        example="7",
        description="Bans all members and purges their recent messages",
    )
    @has_permissions(ban_members=True)
    async def ban_purge(self, ctx, delete_history):
        """Bans all members and purges their recent messages"""
        pass

    @command(
        name="temprole",
        description="No description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole(self, ctx, member, duration, role):
        """give temporary role"""
        pass

    @command(
        name="temprole list",
        description="No description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole_list(self, ctx):
        """list temporary roles"""
        pass

    @command(
        name="dump",
        description="Dumps all members of a role",
    )
    @has_permissions(manage_roles=True)
    async def dump(self, ctx, role, flags):
        """dump role members"""
        pass

    @command(
        name="newmembers",
        description="View list of recently joined members",
    )
    async def newmembers(self, ctx, count):
        """view new members"""
        pass

    @command(
        name="recentban",
        description="Chunk ban recently joined members",
    )
    @has_permissions(ban_members=True)
    async def recentban(self, ctx, count, *, reason):
        """ban recent members"""
        pass

    @command(
        name="talk",
        description="Toggle a channel to text for a role",
    )
    @has_permissions(manage_channels=True)
    async def talk(self, ctx, channel, role):
        """toggle channel text for role"""
        pass

    @command(
        name="unhide",
        description="Unhide a channel from a role or member",
    )
    async def unhide(self, ctx, channel, role_or_member):
        """unhide channel from role or member"""
        pass

    @command(
        name="hide",
        description="Hide a channel from a role or member",
    )
    @has_permissions(manage_channels=True)
    async def hide(self, ctx, channel, role_or_member):
        """hide channel from role or member"""
        pass

    async def _ensure_category(self, ctx, name: str) -> discord.CategoryChannel:
        existing = discord.utils.get(ctx.guild.categories, name=name)
        if existing:
            return existing
        return await ctx.guild.create_category(name, reason="Moderation setup")

    async def _ensure_channel(
        self, ctx, name: str, category: discord.CategoryChannel, topic: str = ""
    ) -> discord.TextChannel:
        existing = discord.utils.get(category.text_channels, name=name)
        if existing:
            return existing
        return await ctx.guild.create_text_channel(
            name, category=category, topic=topic, reason="Moderation setup"
        )

    @command(
        name="setup",
        description="Start process for setting up the moderation system",
    )
    @has_permissions(administrator=True)
    async def setup(self, ctx):
        """setup moderation system"""
        async with ctx.typing():
            overwrites_logs = {
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                ctx.guild.me: discord.PermissionOverwrite(read_messages=True),
            }
            for role in ctx.guild.roles:
                if role.permissions.administrator:
                    overwrites_logs[role] = discord.PermissionOverwrite(read_messages=True)

            logs_cat = await self._ensure_category(ctx, "logs")
            await logs_cat.edit(overwrites=overwrites_logs)

            jail_role_id = None
            jail_row = await self.bot.db.fetchrow(
                "SELECT jail_role_id FROM server_settings WHERE guild_id = $1",
                ctx.guild.id,
            )
            if jail_row and jail_row.get("jail_role_id"):
                jail_role_id = jail_row["jail_role_id"]

            overwrites_jail = {
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
            }
            for role in ctx.guild.roles:
                if role.permissions.administrator:
                    overwrites_jail[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            if jail_role_id:
                jail_role = ctx.guild.get_role(jail_role_id)
                if jail_role:
                    overwrites_jail[jail_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            jail_cat = await self._ensure_category(ctx, "jail")
            await jail_cat.edit(overwrites=overwrites_jail)

            antinuke_ch = await self._ensure_channel(
                ctx, "antinuke-logs", logs_cat, "Antinuke moderation events"
            )
            antiraid_ch = await self._ensure_channel(
                ctx, "antiraid-logs", logs_cat, "Antiraid moderation events"
            )
            jail_logs_ch = await self._ensure_channel(
                ctx, "jail-logs", logs_cat, "Jail moderation events"
            )
            modlog_ch = await self._ensure_channel(
                ctx, "modlogs", logs_cat, "Modlog channel"
            )

            jailed_overwrites = dict(overwrites_jail)
            jailed_ch = await self._ensure_channel(
                ctx, "jailed", jail_cat, "Jail channel for muted members"
            )
            await jailed_ch.edit(overwrites=jailed_overwrites)

            await self.bot.db.execute(
                """INSERT INTO modlog_config (guild_id, channel_id)
                   VALUES ($1, $2)
                   ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2""",
                ctx.guild.id, modlog_ch.id,
            )
            await self.bot.db.execute(
                """INSERT INTO server_settings (guild_id, jail_channel_id)
                   VALUES ($1, $2)
                   ON CONFLICT (guild_id) DO UPDATE SET jail_channel_id = $2""",
                ctx.guild.id, jailed_ch.id,
            )

        await ctx.success(
                f"Moderation system set up has been completed. Please make sure that all of your channels and roles have been configured properly."
            )

    @command(
        name="unsetup",
        aliases=["unsetme", "reset"],
        description="Remove moderation system setup (categories and channels)",
    )
    @has_permissions(administrator=True)
    async def unsetup(self, ctx):
        """remove moderation setup"""
        async with ctx.typing():
            removed = []

            for cat_name in ("logs", "jail"):
                cat = discord.utils.get(ctx.guild.categories, name=cat_name)
                if cat:
                    for ch in cat.channels:
                        await ch.delete(reason="Moderation unsetup")
                        removed.append(f"#{ch.name}")
                    await cat.delete(reason="Moderation unsetup")
                    removed.append(f"Category: {cat_name}")

            await self.bot.db.execute(
                "DELETE FROM modlog_config WHERE guild_id = $1",
                ctx.guild.id,
            )

        if removed:
            await ctx.success(
                f"Removed: {', '.join(removed)}\n"
                f"Use `{ctx.clean_prefix}setup` to recreate them."
            )
        else:
            await ctx.warn("No setup channels found to remove.")

    @command(
        name="setupmute",
        description="Sets up muted roles and channel permissions",
    )
    @has_permissions(manage_guild=True, manage_channels=True)
    async def setupmute(self, ctx):
        """setup mute system"""
        async with ctx.typing():
            muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
            if not muted_role:
                muted_role = await ctx.guild.create_role(
                    name="Muted",
                    reason="Mute system setup",
                    permissions=discord.Permissions(send_messages=False, add_reactions=False),
                )
            imuted_role = discord.utils.get(ctx.guild.roles, name="Image Muted")
            if not imuted_role:
                imuted_role = await ctx.guild.create_role(
                    name="Image Muted",
                    reason="Mute system setup",
                    permissions=discord.Permissions(attach_files=False, embed_links=False),
                )
            rmuted_role = discord.utils.get(ctx.guild.roles, name="Reaction Muted")
            if not rmuted_role:
                rmuted_role = await ctx.guild.create_role(
                    name="Reaction Muted",
                    reason="Mute system setup",
                    permissions=discord.Permissions(add_reactions=False),
                )

            await self.bot.db.execute(
                """INSERT INTO server_settings (guild_id, muted_role_id, imuted_role_id, rmuted_role_id)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (guild_id) DO UPDATE SET
                       muted_role_id = $2, imuted_role_id = $3, rmuted_role_id = $4""",
                ctx.guild.id, muted_role.id, imuted_role.id, rmuted_role.id,
            )

            for channel in ctx.guild.text_channels:
                await channel.set_permissions(muted_role, send_messages=False, add_reactions=False)
                await channel.set_permissions(imuted_role, attach_files=False, embed_links=False)
                await channel.set_permissions(rmuted_role, add_reactions=False)

        embed = discord.Embed(
            color=self.bot.color,
            title="Mute Setup Complete",
            description=(
                f"✅ Created/verified mute roles:\n"
                f"  • {muted_role.mention} (text mute)\n"
                f"  • {imuted_role.mention} (image mute)\n"
                f"  • {rmuted_role.mention} (reaction mute)\n\n"
                f"Permissions have been applied to all text channels."
            ),
        )
        await ctx.send(embed=embed)

    @command(
        name="rename",
        description="Assigns the mentioned user a new nickname in the guild",
    )
    async def rename(self, ctx, member, newnick):
        """rename a member"""
        pass

    @command(
        name="raid",
        description="Remove all members that joined in the time provided in the event of a raid",
    )
    async def raid(self, ctx, time, action, *, reason):
        """raid mode"""
        pass

    @command(
        name="topic",
        description="Change the current channel topic",
    )
    @has_permissions(manage_channels=True)
    async def topic(self, ctx, *, text):
        """change channel topic"""
        pass

    @command(
        name="naughty",
        description="Temporarily make a channel NSFW for 30 seconds",
    )
    @has_permissions(manage_channels=True)
    async def naughty(self, ctx, channel):
        """make channel nsfw temporarily"""
        pass

    @command(
        name="permissions",
        description="Check permissions for member or myself",
    )
    @has_permissions(manage_roles=True, manage_channels=True)
    async def permissions(self, ctx, member, channel):
        """check permissions"""
        pass

    @command(
        name="unlock",
        description="Unlock a channel",
    )
    @has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel, *, reason):
        """unlock a channel"""
        pass

    @command(
        name="unlock all",
        description="Unlocks every channel",
    )
    @has_permissions(manage_channels=True)
    async def unlock_all(self, ctx, *, reason):
        """unlock all channels"""
        pass
