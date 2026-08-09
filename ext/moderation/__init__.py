from __future__ import annotations

import asyncio
import contextlib
import discord
from datetime import timedelta
from typing import Literal
from discord.ext import tasks
from discord.ext import commands
from discord.ext.commands import Greedy, command, group
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.tools.moderation_args import (
    ParsedModerationArgs,
    command_tail,
    format_duration_token,
    parse_amount_and_reason,
    parse_duration_seconds,
    parse_moderation_args,
)
from core.tools.moderation_logs import (
    DEFAULT_INVOKE_DM,
    build_modlog_embed,
    send_invoke_dm,
    send_invoke_response,
)

from core.managers.permissions import has_permissions

from core.discord.views.embed import panel_embed, reply_embed

def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"

class _BoostConfirmView(discord.ui.View):
    """Approve/Decline confirmation when targeting a booster."""

    def __init__(self, ctx, *, action: str, member: discord.Member, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.member = member
        self.value: bool | None = None
        self._action = action

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                f"Only {self.ctx.author.mention} can use this.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()

    async def prompt(self) -> bool:
        embed = reply_embed(
            color=0x2A2B2F,
            message=(
                f"Are you sure you want to **{self._action}** {self.member.mention}?\n"
                f"They are currently boosting the server."
            ),
        )
        msg = await self.ctx.send(embed=embed, view=self)
        await self.wait()
        with contextlib.suppress(discord.HTTPException):
            await msg.delete()
        return bool(self.value)

class ModerationCommands(Package):
    """standalone moderation commands"""

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._unbanall_tasks: dict[int, asyncio.Task] = {}
        self._naughty_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        if self.db.pool is not None:
            self.tempban_watcher.start()
            self.temprole_watcher.start()

    async def cog_unload(self) -> None:
        if self.tempban_watcher.is_running():
            self.tempban_watcher.cancel()
        if self.temprole_watcher.is_running():
            self.temprole_watcher.cancel()
        for task in self._unbanall_tasks.values():
            if not task.done():
                task.cancel()
        for task in self._naughty_tasks.values():
            if not task.done():
                task.cancel()
        self._naughty_tasks.clear()

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
            "y": 31536000,
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

    async def _ensure_jail_ready(self, ctx) -> dict | None:
        raw = await self.db.fetchrow(
            "SELECT jail_channel_id, jail_role_id, jail_remove_roles, jail_message FROM server_settings WHERE guild_id = $1",
            ctx.guild.id,
        )
        
        row: dict = dict(raw) if raw else {}

        jail_role = ctx.guild.get_role(row.get("jail_role_id") or 0)
        if jail_role is None:
            jail_role = discord.utils.get(ctx.guild.roles, name="Jailed")
            if jail_role is None:
                jail_role = await ctx.guild.create_role(
                    name="Jailed",
                    reason="Jail system setup",
                    permissions=discord.Permissions.none(),
                )
            await self.db.set_server_settings(ctx.guild.id, jail_role_id=jail_role.id)
            row["jail_role_id"] = jail_role.id

        jail_channel = ctx.guild.get_channel(row.get("jail_channel_id") or 0)
        if jail_channel is None:
            jail_cat = discord.utils.get(ctx.guild.categories, name="jail")
            if jail_cat is None:
                jail_cat = await ctx.guild.create_category("jail", reason="Jail system setup")
            jail_channel = discord.utils.get(jail_cat.text_channels, name="jailed")
            if jail_channel is None:
                overwrites = {
                    ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    ctx.guild.me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                    ),
                    jail_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                }
                jail_channel = await jail_cat.create_text_channel(
                    "jailed",
                    overwrites=overwrites,
                    reason="Jail system setup",
                )
            await self.db.set_server_settings(ctx.guild.id, jail_channel_id=jail_channel.id)
            row["jail_channel_id"] = jail_channel.id

        await self._sync_jail_permissions(ctx.guild, jail_role, jail_channel)
        row["jail_role"] = jail_role
        row["jail_channel"] = jail_channel
        return row

    async def _sync_jail_permissions(
        self,
        guild: discord.Guild,
        jail_role: discord.Role,
        jail_channel: discord.TextChannel,
    ) -> None:
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                if channel.id == jail_channel.id:
                    await channel.set_permissions(
                        jail_role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    )
                else:
                    await channel.set_permissions(
                        jail_role,
                        view_channel=False,
                        send_messages=False,
                    )
            elif isinstance(channel, discord.VoiceChannel):
                await channel.set_permissions(jail_role, connect=False, speak=False)

    async def _ensure_targetable(self, ctx, member: discord.Member) -> bool:
        """Check if a member can be moderated. Returns True if OK, False if blocked (sends warning)."""
        from core.tools.hierarchy import ensure_member_hierarchy
        from discord.ext.commands import CommandError as _CmdErr

        if ctx.guild is None:
            await ctx.warn("This command can only be used in a server")
            return False
        try:
            await ensure_member_hierarchy(ctx, member, allow_self=False)
        except _CmdErr as e:
            await ctx.warn(str(e))
            return False
        return True

    async def _confirm_if_booster(self, ctx, member: discord.Member, action: str) -> bool:
        """Show approval prompt if the target is boosting. Returns True to proceed."""
        if not getattr(member, "premium_since", None):
            return True
        view = _BoostConfirmView(ctx, action=action, member=member)
        return await view.prompt()

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
        target: discord.abc.User | str | None = None,
        target_name: str | None = None,
        case_id: int | None = None,
        reason: str | None = None,
        extra: str | None = None,
    ) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        channel_id = await self.db.get_modlog_channel(ctx.guild.id)
        if not channel_id:
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        if target_name is not None:
            target_label = target_name
        elif isinstance(target, str):
            target_label = target
        elif target is not None:
            target_label = getattr(target, "mention", None) or str(target)
        else:
            target_label = "Unknown User"
        embed = build_modlog_embed(
            color=self.color,
            action=action,
            target_label=target_label,
            moderator_label=ctx.author.mention,
            reason=self._default_reason(reason),
            case_id=case_id,
            extra=extra,
        )
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def _invoke_dm(
        self,
        ctx,
        member: discord.abc.User,
        action: str,
        *,
        reason: str | None,
        case_id: int | None = None,
        duration: str | None = None,
    ) -> None:
        await send_invoke_dm(
            self.bot,
            self.db,
            member=member,
            guild=ctx.guild,
            moderator=ctx.author,
            action=action,
            reason=reason,
            case_id=case_id,
            duration=duration,
        )

    async def _invoke_response(
        self,
        ctx,
        action: str,
        *,
        user: discord.abc.User,
        reason: str | None,
        case_id: int | None = None,
        duration: str | None = None,
    ) -> bool:
        return await send_invoke_response(
            self.bot,
            self.db,
            ctx,
            action=action,
            user=user,
            moderator=ctx.author,
            reason=reason,
            case_id=case_id,
            duration=duration,
        )

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

    def _format_case_line(self, row) -> str:
        target = f"`{row['target_id']}`" if row.get("target_id") else "unknown"
        moderator = f"`{row['moderator_id']}`" if row.get("moderator_id") else "unknown"
        reason = row.get("reason") or "no reason provided"
        created = row.get("created_at")
        from core.tools.human import human_date

        stamp = human_date(created, fallback="unknown")
        return label_line(
            f"Case #{row['case_id']} · {row['action']}",
            f"{target} · {moderator} · {reason} · {stamp}",
        )

    async def _build_case_embed(self, ctx, case_id: int) -> discord.Embed | None:
        if getattr(self.db, "pool", None) is None:
            return None
        row = await self.db.fetch_modlog_case(ctx.guild.id, int(case_id))
        if not row:
            return None
        target = ctx.guild.get_member(row["target_id"])
        target_label = target.mention if target else f"`{row['target_id']}`"
        moderator = ctx.guild.get_member(row["moderator_id"])
        moderator_label = moderator.mention if moderator else f"`{row['moderator_id']}`"
        return build_modlog_embed(
            color=self.color,
            action=str(row["action"]),
            target_label=target_label,
            moderator_label=moderator_label,
            reason=row.get("reason") or "no reason provided",
            case_id=row["case_id"],
        )

    async def _ban_member(
        self,
        ctx,
        member: discord.Member,
        *,
        reason: str | None,
        delete_days: int = 0,
        action: str = "ban",
        duration_label: str | None = None,
        respond: bool = True,
    ) -> bool:
        if not await self._ensure_targetable(ctx, member):
            return False
        if respond and not await self._confirm_if_booster(ctx, member, action):
            await ctx.warn("Action cancelled.")
            return False
        if not respond and getattr(member, "premium_since", None):
            return False

        role_ids = [role.id for role in member.roles if role != ctx.guild.default_role]
        target_display = str(member)
        target_id = member.id

        case_id = await self._create_case(
            ctx,
            action=action,
            target_id=target_id,
            reason=reason,
        )
        if action in DEFAULT_INVOKE_DM:
            await self._invoke_dm(
                ctx,
                member,
                action,
                reason=reason,
                case_id=case_id,
                duration=duration_label,
            )

        await member.ban(
            delete_message_seconds=delete_days * 86400,
            reason=self._audit_reason(ctx, reason),
        )
        extra_parts = []
        if delete_days:
            extra_parts.append(f"**Message purge** : {delete_days} day(s)")
        if duration_label:
            extra_parts.append(f"**Duration** : {duration_label}")
        await self._send_modlog(
            ctx,
            action=action,
            target=member,
            case_id=case_id,
            reason=reason,
            extra="\n".join(extra_parts) if extra_parts else None,
        )
        self._dispatch_antinuke_action(
            ctx,
            action=action,
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        if respond:
            if await self._invoke_response(
                ctx,
                action,
                user=member,
                reason=reason,
                case_id=case_id,
                duration=duration_label,
            ):
                return True
            purge = f" (purged **{delete_days}d**)" if delete_days else ""
            duration = f" for **{duration_label}**" if duration_label else ""
            await ctx.success(
                f"{action.title()}ned **{target_display}**{duration}{purge} - {self._default_reason(reason)}"
            )
        return True

    async def _run_tempban(
        self,
        ctx,
        parsed: ParsedModerationArgs,
        *,
        duration_token: str | None = None,
    ) -> None:
        member = parsed.member
        reason = parsed.reason
        if not await self._ensure_targetable(ctx, member):
            return
        if not await self._confirm_if_booster(ctx, member, "tempban"):
            return await ctx.warn("Action cancelled.")

        seconds = parsed.duration_seconds
        if duration_token:
            seconds = parse_duration_seconds(duration_token) or self._parse_duration_seconds(duration_token)
        if not seconds or seconds < 1:
            raise CommandError("duration must look like `30m`, `2h`, `7d`, `1w`, or `1y`")

        target_display = str(member)
        target_id = member.id
        role_ids = [role.id for role in member.roles if role != ctx.guild.default_role]
        unban_at = discord.utils.utcnow() + timedelta(seconds=seconds)
        duration_label = self._format_duration(seconds)

        case_id = await self._create_case(
            ctx,
            action="tempban",
            target_id=target_id,
            reason=reason,
        )
        await self._invoke_dm(
            ctx,
            member,
            "tempban",
            reason=reason,
            case_id=case_id,
            duration=duration_label,
        )

        await member.ban(
            delete_message_seconds=0,
            reason=self._audit_reason(ctx, reason),
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
            extra=f"**Duration** : {duration_label}",
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
        if await self._invoke_response(
            ctx,
            "tempban",
            user=member,
            reason=reason,
            case_id=case_id,
            duration=duration_label,
        ):
            return
        return await ctx.success(
            f"Tempbanned **{target_display}** for **{duration_label}** - {self._default_reason(reason)}"
        )

    @command(
        name="tempban",
        usage="(duration) (member) <reason>",
        example="3h @member spamming",
        description="Temporarily ban a member",
    )
    @has_permissions(ban_members=True)
    async def tempban(self, ctx):
        """temporarily ban a member"""
        parsed = await parse_moderation_args(ctx, command_names=("tempban",), allow_duration=True)
        if not parsed.duration_seconds:
            raise CommandError("you must provide a duration like `3h`, `2d`, `1w`, or `1y`")
        await self._run_tempban(ctx, parsed)

    @command(
        name="warn",
        description="Warns the mentioned user and private messages them the warning",
    )
    @has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason=None):
        """warn a member"""
        if not await self._ensure_targetable(ctx, member):
            return

        case_id = await self._create_case(
            ctx,
            action="warn",
            target_id=member.id,
            reason=reason,
        )
        await self._invoke_dm(ctx, member, "warn", reason=reason, case_id=case_id)
        await self._send_modlog(
            ctx,
            action="warn",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        if await self._invoke_response(ctx, "warn", user=member, reason=reason, case_id=case_id):
            return
        return await ctx.success(
            f"Warned **{member}** - {self._default_reason(reason)}"
        )

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
        aliases=["strip"],
        description="Remove all roles with dangerous permissions from a member",
    )
    @has_permissions(manage_roles=True)
    async def stripstaff(self, ctx, *, member: discord.Member):
        """strip dangerous/staff roles from member"""
        if member.id == ctx.author.id:
            return await ctx.warn("You cannot **strip yourself** of staff roles")

        if member.id == ctx.guild.owner_id:
            return await ctx.warn("You cannot strip the **server owner**")

        if ctx.author.top_role <= member.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.warn("Your top role must be **higher** than this member's top role")

        from core.tools.convert.role import DANGEROUS_PERMISSIONS

        removed = []
        for role in list(member.roles):
            if role.is_default() or role.managed:
                continue
            if role >= ctx.guild.me.top_role:
                continue
            if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
                continue
            has_dangerous = any(getattr(role.permissions, perm, False) for perm in DANGEROUS_PERMISSIONS)
            if has_dangerous:
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
        usage="[duration] (member) <reason>",
        example="2d @member spamming",
        description="Jails the mentioned user",
    )
    @has_permissions(manage_messages=True)
    async def jail(self, ctx):
        """jail a member"""
        parsed = await parse_moderation_args(ctx, command_names=("jail",), allow_duration=True)
        member = parsed.member
        reason = parsed.reason
        if not await self._ensure_targetable(ctx, member):
            return

        row = await self._ensure_jail_ready(ctx)
        if not row:
            return await ctx.warn("Failed to configure jail - try `,setupjail`")

        jail_role = row["jail_role"]
        jail_channel = row["jail_channel"]

        existing = await self.db.fetchrow(
            "SELECT 1 FROM jailed WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, member.id,
        )
        if existing:
            return await ctx.warn(f"**{member}** is already jailed")

        role_ids = [r.id for r in member.roles if r != ctx.guild.default_role]

        try:
            if row.get("jail_remove_roles", True) and role_ids:
                roles_to_remove = [ctx.guild.get_role(rid) for rid in role_ids if ctx.guild.get_role(rid)]
                if roles_to_remove:
                    await member.remove_roles(
                        *roles_to_remove,
                        reason=f"Jailed by {ctx.author}: {self._default_reason(reason)}",
                    )
            await member.add_roles(
                jail_role,
                reason=f"Jailed by {ctx.author}: {self._default_reason(reason)}",
            )
        except discord.Forbidden:
            return await ctx.warn("I don't have permission to manage this member's roles")
        except discord.HTTPException as e:
            return await ctx.warn(f"Failed to update roles: {e}")

        if member.voice and member.voice.channel:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await member.move_to(None, reason=f"Jailed by {ctx.author}")

        await self.db.execute(
            """INSERT INTO jailed (guild_id, user_id, role_ids, moderator_id, reason)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (guild_id, user_id) DO UPDATE
               SET role_ids = $3, moderator_id = $4, reason = $5, jailed_at = CURRENT_TIMESTAMP""",
            ctx.guild.id, member.id, role_ids, ctx.author.id, reason,
        )

        case_id = await self._create_case(
            ctx, action="jail", target_id=member.id, reason=reason,
        )
        await self._invoke_dm(ctx, member, "jail", reason=reason, case_id=case_id)
        await self._send_modlog(
            ctx, action="jail", target=member, case_id=case_id, reason=reason,
        )

        jail_message = row.get("jail_message")
        if jail_message:
            with contextlib.suppress(Exception):
                await self.bot.send_embed(
                    jail_channel,
                    jail_message,
                    user=member,
                    member=member,
                    moderator=ctx.author,
                    guild=ctx.guild,
                    reason=self._default_reason(reason),
                )
        else:
            embed = build_modlog_embed(
                color=self.color,
                action="jailed",
                target_label=member.mention,
                moderator_label=ctx.author.mention,
                reason=self._default_reason(reason),
                case_id=case_id,
            )
            await jail_channel.send(content=member.mention, embed=embed)

        if await self._invoke_response(ctx, "jail", user=member, reason=reason, case_id=case_id):
            return
        return await ctx.success(
            f"Jailed **{member}** in {jail_channel.mention} - {self._default_reason(reason)}"
        )

    @command(
        name="unjail",
        description="Unjails the mentioned user",
    )
    @has_permissions(manage_messages=True)
    async def unjail(self, ctx, member: discord.Member, *, reason=None):
        """unjail a member"""
        row = await self.db.fetchrow(
            "SELECT * FROM jailed WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, member.id,
        )
        if not row:
            return await ctx.warn(f"**{member}** is not jailed")

        role_ids = row["role_ids"]
        jail_role_id = (await self.db.fetchrow(
            "SELECT jail_role_id FROM server_settings WHERE guild_id = $1",
            ctx.guild.id,
        ))
        jail_role_id = jail_role_id["jail_role_id"] if jail_role_id else None

        
        try:
            if jail_role_id:
                jail_role = ctx.guild.get_role(jail_role_id)
                if jail_role and jail_role in member.roles:
                    await member.remove_roles(jail_role, reason=f"Unjailed by {ctx.author}")

            roles_to_add = [ctx.guild.get_role(rid) for rid in role_ids if ctx.guild.get_role(rid)]
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason=f"Unjailed by {ctx.author}")
        except discord.Forbidden:
            return await ctx.warn("I don't have permission to manage this member's roles")
        except discord.HTTPException as e:
            return await ctx.warn(f"Failed to restore roles: {e}")

        
        await self.db.execute(
            "DELETE FROM jailed WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, member.id,
        )

        case_id = await self._create_case(
            ctx, action="unjail", target_id=member.id, reason=reason,
        )
        await self._invoke_dm(ctx, member, "unjail", reason=reason, case_id=case_id)
        await self._send_modlog(
            ctx, action="unjail", target=member, case_id=case_id, reason=reason,
        )
        if await self._invoke_response(ctx, "unjail", user=member, reason=reason, case_id=case_id):
            return
        return await ctx.success(f"Unjailed **{member}** - {self._default_reason(reason)}")

    @command(
        name="modstats",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def modstats(self, ctx, member: discord.Member):
        """view moderation stats for a member"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        total = await self.db.count_modlog_cases(ctx.guild.id, member.id)
        warns = await self.db.count_modlog_cases(ctx.guild.id, member.id, action="warn")
        as_staff = len(
            await self.db.fetch_modlog_cases_by_moderator(ctx.guild.id, member.id, limit=1000)
        )
        embed = panel_embed(
            title="Moderation Stats",
            color=self.color,
            lines=[
                label_line("Member", member.mention),
                label_line("Cases against", str(total)),
                label_line("Warnings", str(warns)),
                label_line("Actions taken", str(as_staff)),
            ],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="warnings",
        description="View warnings for a member",
    )
    @has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member):
        """view warnings for a member"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        rows = await self.db.fetch_modlog_cases_for_user(
            ctx.guild.id, member.id, action="warn", limit=25
        )
        if not rows:
            return await ctx.warn(f"{member.mention} has **no warnings**")
        embed = panel_embed(
            title=f"Warnings - {member}",
            color=self.color,
            lines=[self._format_case_line(row) for row in rows],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="moderationhistory",
        description="View moderation actions from a staff member",
    )
    @has_permissions(manage_messages=True)
    async def moderationhistory(self, ctx, member: discord.Member, command: str | None = None):
        """view moderation history for a staff member"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        rows = await self.db.fetch_modlog_cases_by_moderator(
            ctx.guild.id,
            member.id,
            action=command.lower() if command else None,
            limit=25,
        )
        if not rows:
            return await ctx.warn(f"{member.mention} has **no recorded actions**")
        title = f"Moderation History - {member}"
        if command:
            title += f" ({command})"
        embed = panel_embed(
            title=title,
            color=self.color,
            lines=[self._format_case_line(row) for row in rows],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="jaillist",
        description="View a list of every current jailed member",
    )
    @has_permissions(manage_messages=True)
    async def jaillist(self, ctx):
        """list all jailed members"""
        rows = await self.db.fetch(
            "SELECT user_id, moderator_id, reason, jailed_at FROM jailed WHERE guild_id = $1 ORDER BY jailed_at DESC",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No members are currently jailed")

        lines = []
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            name = member.mention if member else f"`{row['user_id']}`"
            mod = ctx.guild.get_member(row["moderator_id"])
            mod_name = mod.mention if mod else "`unknown`"
            reason = row["reason"] or "no reason"
            lines.append(label_line(name, f"jailed by {mod_name} - {reason}"))

        embed = panel_embed(
            title="Jailed Members",
            color=self.color,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="caselog",
        description="View a case log",
    )
    @has_permissions(manage_messages=True)
    async def caselog(self, ctx, case_id: int):
        """view case log"""
        embed = await self._build_case_embed(ctx, case_id)
        if embed is None:
            return await ctx.warn(f"Case **#{case_id}** was not found")
        await ctx.send(embed=embed)

    @group(
        name="timeout",
        aliases=["mute", "silence"],
        description="Timeout a member using Discord's timeout feature",
        example=",timeout @member 30m spamming",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True)
    async def timeout(self, ctx):
        """Timeout a member (aliases: mute, silence)."""
        parsed = await parse_moderation_args(
            ctx, command_names=("timeout", "mute", "silence"), allow_duration=True
        )
        if parsed.member is None:
            return await ctx.send_help(ctx.command)

        member = parsed.member
        if not await self._ensure_targetable(ctx, member):
            return

        seconds = parsed.duration_seconds or (60 * 60)
        if seconds < 60:
            return await ctx.warn("Duration must be at least **60 seconds**")
        if seconds > 28 * 86400:
            return await ctx.warn("Duration cannot exceed **28 days**")

        reason = parsed.reason
        duration_label = self._format_duration(seconds)
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        case_id = await self._create_case(
            ctx, action="timeout", target_id=member.id, reason=reason,
        )
        await self._invoke_dm(
            ctx, member, "timeout", reason=reason, case_id=case_id, duration=duration_label,
        )
        try:
            await member.timeout(until, reason=self._audit_reason(ctx, reason))
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to timeout this member")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to timeout **{member}**: {e}")

        await self._send_modlog(
            ctx,
            action="timeout",
            target=member,
            case_id=case_id,
            reason=reason,
            extra=f"**Duration** : {duration_label}",
        )
        if await self._invoke_response(
            ctx, "timeout", user=member, reason=reason, case_id=case_id, duration=duration_label,
        ):
            return
        return await ctx.success(
            f"Timed out **{member}** for **{duration_label}** - {self._default_reason(reason)}"
        )

    @timeout.command(
        name="list",
        description="View list of timed out members",
    )
    @has_permissions(moderate_members=True)
    async def timeout_list(self, ctx):
        """list timed out members"""
        now = discord.utils.utcnow()
        timed_out = [
            member
            for member in ctx.guild.members
            if member.timed_out_until and member.timed_out_until > now
        ]
        if not timed_out:
            return await ctx.warn("No members are currently **timed out**")
        lines = []
        for member in timed_out[:25]:
            remaining = discord.utils.format_dt(member.timed_out_until, style="R")
            lines.append(label_line(str(member), f"until {remaining}"))
        embed = panel_embed(
            title="Timed Out Members",
            color=self.color,
            lines=lines,
            footer=f"{len(timed_out)} total" if len(timed_out) > 25 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="untimeout",
        aliases=["unmute"],
        description="Removes a timeout for a member",
        example=",untimeout @member",
    )
    @has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason=None):
        """remove timeout from a member"""
        if not member.timed_out_until or member.timed_out_until <= discord.utils.utcnow():
            return await ctx.warn(f"{member.mention} is not **timed out**")
        case_id = await self._create_case(
            ctx, action="untimeout", target_id=member.id, reason=reason,
        )
        await self._invoke_dm(ctx, member, "untimeout", reason=reason, case_id=case_id)
        try:
            await member.timeout(None, reason=self._audit_reason(ctx, reason))
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to remove this timeout")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to remove timeout: {e}")
        await self._send_modlog(
            ctx, action="untimeout", target=member, case_id=case_id, reason=reason,
        )
        if await self._invoke_response(ctx, "untimeout", user=member, reason=reason, case_id=case_id):
            return
        return await ctx.success(
            f"Removed timeout for **{member}** - {self._default_reason(reason)}"
        )

    async def _mute_member(
        self,
        ctx,
        member: discord.Member,
        mute_type: str,
        *,
        duration: str | None = None,
        reason: str | None = None,
    ):
        if not await self._ensure_targetable(ctx, member):
            return

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
        seconds = None
        if duration:
            seconds = self._parse_duration_seconds(duration)
            if not seconds:
                return await ctx.warn(f"Invalid duration `{duration}`. Examples: `30m`, `2h`, `7d`.")
            expires_at = discord.utils.utcnow() + timedelta(seconds=seconds)

        if role in member.roles:
            return await ctx.warn(f"**{member}** is already {role_label}.")

        case_id = await self._create_case(
            ctx, action=role_label, target_id=member.id, reason=reason,
        )
        duration_label = (
            self._format_duration(seconds) if duration and expires_at and seconds else None
        )
        if mute_type == "":
            await self._invoke_dm(
                ctx,
                member,
                "mute",
                reason=reason,
                case_id=case_id,
                duration=duration_label,
            )

        await member.add_roles(role, reason=self._audit_reason(ctx, reason))
        await self.bot.db.execute(
            """INSERT INTO mutes (guild_id, user_id, moderator_id, mute_type, role_id, expires_at, reason)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (guild_id, user_id) DO UPDATE
               SET mute_type = $4, role_id = $5, expires_at = $6, reason = $7, moderator_id = $3""",
            ctx.guild.id, member.id, ctx.author.id, mute_type or "text",
            role.id, expires_at, self._default_reason(reason),
        )
        await self._send_modlog(
            ctx,
            action=role_label,
            target=member,
            case_id=case_id,
            reason=reason,
            extra=f"**Duration** : {duration_label}" if duration_label else None,
        )
        self._dispatch_antinuke_action(
            ctx, action=role_label, case_id=case_id,
            meta={"target_id": member.id, "target_display": str(member)},
        )

        if mute_type == "" and await self._invoke_response(
            ctx, "mute", user=member, reason=reason, case_id=case_id, duration=duration_label
        ):
            return
        parts = [f"{role_label.title()} **{member}**"]
        if duration_label:
            parts.append(f"for **{duration_label}**")
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
        if mute_type == "":
            await self._invoke_dm(ctx, member, "unmute", reason=reason)
            if await self._invoke_response(ctx, "unmute", user=member, reason=reason):
                return
        return await ctx.success(f"Un{mute_type if mute_type else 'mute'}d **{member}** - {self._default_reason(reason)}")

    async def _resolve_member_or_role(self, ctx, target: str):
        """Resolve a message token to a Member or Role."""
        raw = (target or "").strip()
        if not raw:
            return None
        with contextlib.suppress(Exception):
            return await commands.MemberConverter().convert(ctx, raw)
        with contextlib.suppress(Exception):
            return await commands.RoleConverter().convert(ctx, raw)
        return None

    async def _apply_special_mute(
        self,
        ctx,
        target: discord.Member | discord.Role,
        mute_type: Literal["i", "r"],
        *,
        reason: str | None = None,
        remove: bool = False,
    ):
        """Image/reaction mute a single member, or every member with a role."""
        if isinstance(target, discord.Role):
            members = [m for m in target.members if not m.bot]
            if not members:
                return await ctx.warn(f"No members found with {target.mention}")
            ok = 0
            for member in members:
                try:
                    if remove:
                        await self._unmute_member(ctx, member, mute_type, reason=reason)
                    else:
                        await self._mute_member(ctx, member, mute_type, reason=reason)
                    ok += 1
                except Exception:
                    continue
            label = "image" if mute_type == "i" else "reaction"
            verb = "unmuted" if remove else "muted"
            return await ctx.success(
                f"{label.title()}-{verb} **{ok}** member(s) with {target.mention}"
            )

        if remove:
            return await self._unmute_member(ctx, target, mute_type, reason=reason)
        return await self._mute_member(ctx, target, mute_type, reason=reason)

    @command(
        name="imagemute",
        aliases=["imute", "imgmute"],
        description="Image mute a member or role",
        example=",imagemute @member",
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def imagemute(self, ctx, target: str, *, reason: str | None = None):
        """Image mute a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Couldn't find a member or role matching `{target}`")
        return await self._apply_special_mute(ctx, resolved, "i", reason=reason)

    @command(
        name="imageunmute",
        aliases=["iunmute", "unimagemute"],
        description="Remove image mute from a member or role",
        example=",imageunmute @member",
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def imageunmute(self, ctx, target: str, *, reason: str | None = None):
        """Remove image mute from a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Couldn't find a member or role matching `{target}`")
        return await self._apply_special_mute(
            ctx, resolved, "i", reason=reason, remove=True
        )

    @command(
        name="reactionmute",
        aliases=["rmute", "reactmute"],
        description="Reaction mute a member or role",
        example=",reactionmute @member",
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def reactionmute(self, ctx, target: str, *, reason: str | None = None):
        """Reaction mute a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Couldn't find a member or role matching `{target}`")
        return await self._apply_special_mute(ctx, resolved, "r", reason=reason)

    @command(
        name="reactionunmute",
        aliases=["runmute", "unreactionmute"],
        description="Remove reaction mute from a member or role",
        example=",reactionunmute @member",
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def reactionunmute(self, ctx, target: str, *, reason: str | None = None):
        """Remove reaction mute from a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Couldn't find a member or role matching `{target}`")
        return await self._apply_special_mute(
            ctx, resolved, "r", reason=reason, remove=True
        )

    @command(
        name="hardban",
        description="Keep a member banned",
    )
    @has_permissions(ban_members=True)
    async def hardban(self, ctx, member: discord.Member, *, reason=None):
        """hardban a member"""
        if not await self._ensure_targetable(ctx, member):
            return
        if not await self._confirm_if_booster(ctx, member, "hardban"):
            return await ctx.warn("Action cancelled.")

        case_id = await self._create_case(
            ctx, action="hardban", target_id=member.id, reason=reason,
        )
        try:
            await member.ban(
                delete_message_seconds=0,
                reason=self._audit_reason(ctx, reason),
            )
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to ban this member")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to hardban **{member}**: {e}")

        if getattr(self.db, "pool", None) is not None:
            await self.db.add_hardban(
                ctx.guild.id,
                member.id,
                ctx.author.id,
                self._default_reason(reason),
            )

        await self._send_modlog(
            ctx, action="hardban", target=member, case_id=case_id, reason=reason,
        )
        if await self._invoke_response(ctx, "hardban", user=member, reason=reason, case_id=case_id):
            return
        return await ctx.success(
            f"Hardbanned **{member}** - {self._default_reason(reason)}"
        )

    @command(
        name="hardban list",
        description="View list of hardbanned members",
    )
    @has_permissions(administrator=True)
    async def hardban_list(self, ctx):
        """list hardbanned members"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        rows = await self.db.fetch_hardbans(ctx.guild.id)
        if not rows:
            return await ctx.warn("No **hardbanned** members")
        lines = []
        for row in rows[:25]:
            user = self.bot.get_user(row["user_id"]) or f"`{row['user_id']}`"
            reason = row.get("reason") or "no reason provided"
            lines.append(label_line(str(user), reason))
        embed = panel_embed(
            title="Hardbanned Members",
            color=self.color,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="clearinvites",
        description="Remove all existing invites in guild",
    )
    @has_permissions(manage_guild=True)
    async def clearinvites(self, ctx, params: str | None = None):
        """clear all invites"""
        from core.discord.views.confirm import ConfirmView

        invites = await ctx.guild.invites()
        if not invites:
            return await ctx.warn("This server has **no invites**")
        view = ConfirmView(ctx)
        emb = reply_embed(
            color=0x2A2B2F,
            message=(
                f"This will **delete all invites** in this server (**{len(invites)}**).\n"
                f"Are you sure you want to do this?"
            ),
        )
        if not await view.prompt(embed=emb):
            return await ctx.warn("Clearinvites **cancelled**")
        deleted = 0
        for invite in invites:
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await invite.delete(reason=f"clearinvites by {ctx.author}")
                deleted += 1
        return await ctx.success(f"Deleted **{deleted}** invite(s)")

    @command(
        name="drag",
        description="Drag member(s) to the specified Voice Channel",
    )
    @has_permissions(move_members=True)
    async def drag(
        self,
        ctx,
        members: Greedy[discord.Member],
        channel: discord.VoiceChannel,
    ):
        """drag members to voice channel"""
        if not members:
            return await ctx.warn("You must mention at least **one member**")
        moved = 0
        for member in members:
            if not member.voice or not member.voice.channel:
                continue
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await member.move_to(channel, reason=f"drag by {ctx.author}")
                moved += 1
        if not moved:
            return await ctx.warn("No members could be moved")
        return await ctx.success(f"Moved **{moved}** member(s) to {channel.mention}")

    @command(
        name="unbanall",
        description="Unbans every member in a guild",
    )
    @has_permissions(ban_members=True)
    async def unbanall(self, ctx):
        """unban all members"""
        existing = self._unbanall_tasks.get(ctx.guild.id)
        if existing and not existing.done():
            return await ctx.warn("An **unban all** task is already running")

        try:
            bans = [entry async for entry in ctx.guild.bans()]
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to view bans")

        if not bans:
            return await ctx.warn("No members are **banned**")

        channel = ctx.channel

        async def _run() -> None:
            count = 0
            for entry in bans:
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    await ctx.guild.unban(
                        entry.user,
                        reason=f"unbanall by {ctx.author}",
                    )
                    count += 1
                    await asyncio.sleep(0.75)
            embed = reply_embed(
                color=self.color,
                message=f"Unbanned **{count}** member(s)",
            )
            with contextlib.suppress(discord.HTTPException):
                await channel.send(embed=embed)

        task = asyncio.create_task(_run())
        self._unbanall_tasks[ctx.guild.id] = task
        return await ctx.success(f"Started unbanning **{len(bans)}** member(s)")

    @command(
        name="unbanall cancel",
        description="Cancels a unban all task running",
    )
    @has_permissions(ban_members=True)
    async def unbanall_cancel(self, ctx):
        """cancel unban all task"""
        task = self._unbanall_tasks.get(ctx.guild.id)
        if not task or task.done():
            return await ctx.warn("No **unban all** task is running")
        task.cancel()
        self._unbanall_tasks.pop(ctx.guild.id, None)
        return await ctx.success("Cancelled the **unban all** task")

    @command(
        name="unban",
        usage="(user id or mention) <reason>",
        example="1269433308945711135 appealed",
        description="Unbans the mentioned user",
    )
    @has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason=None):
        """unban a user"""
        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound:
            return await ctx.warn(f"**{user}** is not banned")
        except discord.Forbidden:
            return await ctx.warn("I don't have permission to view the ban list")

        case_id = await self._create_case(
            ctx,
            action="unban",
            target_id=user.id,
            reason=reason,
        )
        await self._invoke_dm(ctx, user, "unban", reason=reason, case_id=case_id)

        try:
            await ctx.guild.unban(
                user,
                reason=self._audit_reason(ctx, reason),
            )
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to unban members")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to unban **{user}**: {e}")

        if getattr(self.db, "pool", None) is not None:
            with contextlib.suppress(Exception):
                await self.db.remove_tempban(ctx.guild.id, user.id)

        await self._send_modlog(
            ctx,
            action="unban",
            target=user,
            case_id=case_id,
            reason=reason,
        )
        if await self._invoke_response(ctx, "unban", user=user, reason=reason, case_id=case_id):
            return
        return await ctx.success(
            f"Unbanned **{user}** - {self._default_reason(reason)}"
        )

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
        if not await self._ensure_targetable(ctx, member):
            return
        if not await self._confirm_if_booster(ctx, member, "softban"):
            return await ctx.warn("Action cancelled.")

        delete_days = self._coerce_delete_days(delete_history, default=1)
        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        target_display = str(member)
        target_id = member.id

        case_id = await self._create_case(
            ctx,
            action="softban",
            target_id=target_id,
            reason=reason,
        )
        await self._invoke_dm(ctx, member, "softban", reason=reason, case_id=case_id)

        await member.ban(
            delete_message_seconds=delete_days * 86400,
            reason=self._audit_reason(ctx, reason),
        )
        await ctx.guild.unban(
            discord.Object(id=target_id),
            reason=self._audit_reason(ctx, "softban removal"),
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
        if await self._invoke_response(ctx, "softban", user=member, reason=reason, case_id=case_id):
            return
        return await ctx.success(
            f"Softbanned **{target_display}** - {self._default_reason(reason)}"
        )

    @command(
        name="ban",
        usage="[duration] (member) [delete history] <reason>",
        example="2d @member Threatening members",
        description="Bans the mentioned user",
    )
    @has_permissions(ban_members=True)
    async def ban(self, ctx):
        """Bans the mentioned user"""
        parsed = await parse_moderation_args(
            ctx,
            command_names=("ban",),
            allow_duration=True,
            allow_delete_days=True,
        )
        if parsed.duration_seconds:
            return await self._run_tempban(ctx, parsed)

        member = parsed.member
        reason = parsed.reason
        if not await self._ensure_targetable(ctx, member):
            return
        if not await self._confirm_if_booster(ctx, member, "ban"):
            return await ctx.warn("Action cancelled.")

        delete_days = parsed.delete_days or 0
        role_ids = [role.id for role in member.roles if role != ctx.guild.default_role]
        target_display = str(member)
        target_id = member.id

        case_id = await self._create_case(
            ctx,
            action="ban",
            target_id=target_id,
            reason=reason,
        )
        await self._invoke_dm(ctx, member, "ban", reason=reason, case_id=case_id)

        await member.ban(
            delete_message_seconds=delete_days * 86400,
            reason=self._audit_reason(ctx, reason),
        )
        await self._send_modlog(
            ctx,
            action="ban",
            target=member,
            case_id=case_id,
            reason=reason,
            extra=f"**Message purge** : {delete_days} day(s)" if delete_days else None,
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
        if await self._invoke_response(ctx, "ban", user=member, reason=reason, case_id=case_id):
            return
        purge = f" (purged **{delete_days}d**)" if delete_days else ""
        return await ctx.success(
            f"Banned **{target_display}**{purge} - {self._default_reason(reason)}"
        )

    @command(
        name="kick",
        usage="(member) <reason>",
        example="@member spamming",
        description="Kick the mentioned user",
    )
    @has_permissions(kick_members=True)
    async def kick(self, ctx):
        """kick a member"""
        parsed = await parse_moderation_args(ctx, command_names=("kick",), allow_duration=False)
        member = parsed.member
        reason = parsed.reason
        if not await self._ensure_targetable(ctx, member):
            return
        if not await self._confirm_if_booster(ctx, member, "kick"):
            return await ctx.warn("Action cancelled.")

        role_ids = [role.id for role in member.roles if role != ctx.guild.default_role]
        target_display = str(member)
        target_id = member.id

        case_id = await self._create_case(
            ctx,
            action="kick",
            target_id=target_id,
            reason=reason,
        )
        await self._invoke_dm(ctx, member, "kick", reason=reason, case_id=case_id)

        await member.kick(reason=self._audit_reason(ctx, reason))
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
        if await self._invoke_response(ctx, "kick", user=member, reason=reason, case_id=case_id):
            return
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
        tail = command_tail(ctx, ("ban", "recent"))
        amount, reason = parse_amount_and_reason(tail, max_amount=50)
        members = sorted(
            [m for m in ctx.guild.members if not m.bot],
            key=lambda m: m.joined_at or discord.utils.utcnow(),
            reverse=True,
        )[:amount]
        if not members:
            return await ctx.warn("No members found to ban")
        banned = 0
        for member in members:
            if member.id in {ctx.author.id, ctx.guild.owner_id, ctx.guild.me.id}:
                continue
            if not await self._ensure_targetable(ctx, member):
                continue
            if await self._ban_member(
                ctx, member, reason=reason, delete_days=0, action="ban", respond=False,
            ):
                banned += 1
        return await ctx.success(f"Banned **{banned}** recently joined member(s)")

    @command(
        name="ban purge",
        usage="(delete history)",
        example="7",
        description="Bans all members and purges their recent messages",
    )
    @has_permissions(ban_members=True)
    async def ban_purge(self, ctx, delete_history: str):
        """Bans all members and purges their recent messages"""
        delete_days = self._coerce_delete_days(delete_history, default=0)
        members = [
            m for m in ctx.guild.members
            if not m.bot and m.id not in {ctx.author.id, ctx.guild.owner_id, ctx.guild.me.id}
        ]
        if not members:
            return await ctx.warn("No members found to ban")
        banned = 0
        for member in members:
            if not await self._ensure_targetable(ctx, member):
                continue
            if await self._ban_member(
                ctx,
                member,
                reason="ban purge",
                delete_days=delete_days,
                action="ban",
                respond=False,
            ):
                banned += 1
        return await ctx.success(
            f"Banned **{banned}** member(s) with **{delete_days}d** message purge"
        )

    @command(
        name="temprole",
        description="No description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole(self, ctx, member: discord.Member, duration: str, role: discord.Role):
        """give temporary role"""
        if not await self._ensure_targetable(ctx, member):
            return
        if role >= ctx.guild.me.top_role:
            return await ctx.warn("That role is **higher** than my top role")
        seconds = self._parse_duration_seconds(duration)
        if not seconds or seconds < 60:
            return await ctx.warn("Duration must be at least **60 seconds**")
        expires_at = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await member.add_roles(role, reason=f"temprole by {ctx.author}")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to add role: {e}")
        if getattr(self.db, "pool", None) is not None:
            await self.db.add_temprole(
                ctx.guild.id, member.id, role.id, expires_at, ctx.author.id,
            )
        label = self._format_duration(seconds)
        return await ctx.success(
            f"Gave {role.mention} to **{member}** for **{label}**"
        )

    @command(
        name="temprole list",
        description="No description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole_list(self, ctx):
        """list temporary roles"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        rows = await self.db.fetch_temproles(ctx.guild.id)
        if not rows:
            return await ctx.warn("No **temporary roles** are active")
        lines = []
        for row in rows[:25]:
            member = ctx.guild.get_member(row["user_id"])
            role = ctx.guild.get_role(row["role_id"])
            member_label = member.mention if member else f"`{row['user_id']}`"
            role_label = role.mention if role else f"`{row['role_id']}`"
            expires = row["expires_at"]
            when = discord.utils.format_dt(expires, style="R") if expires else "unknown"
            lines.append(label_line(f"{member_label} · {role_label}", f"expires {when}"))
        embed = panel_embed(
            title="Temporary Roles",
            color=self.color,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="dump",
        description="Dumps all members of a role",
    )
    @has_permissions(manage_roles=True)
    async def dump(self, ctx, role: discord.Role, flags: str | None = None):
        """dump role members"""
        members = role.members
        if not members:
            return await ctx.warn(f"No members have {role.mention}")
        lines = [member.mention for member in members[:50]]
        embed = panel_embed(
            title=f"Members - {role.name}",
            color=role.color.value or self.color,
            lines=lines,
            footer=f"{len(members)} total" if len(members) > 50 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="newmembers",
        description="View list of recently joined members",
    )
    async def newmembers(self, ctx, count: int = 10):
        """view new members"""
        count = max(1, min(count, 50))
        members = sorted(
            [m for m in ctx.guild.members if m.joined_at],
            key=lambda m: m.joined_at,
            reverse=True,
        )[:count]
        if not members:
            return await ctx.warn("No members found")
        lines = [
            label_line(
                member.mention,
                discord.utils.format_dt(member.joined_at, style="R"),
            )
            for member in members
        ]
        embed = panel_embed(
            title="Recently Joined",
            color=self.color,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="recentban",
        description="Chunk ban recently joined members",
    )
    @has_permissions(ban_members=True)
    async def recentban(self, ctx, count: int, *, reason: str | None = None):
        """ban recent members"""
        count = max(1, min(count, 50))
        members = sorted(
            [m for m in ctx.guild.members if not m.bot],
            key=lambda m: m.joined_at or discord.utils.utcnow(),
            reverse=True,
        )[:count]
        banned = 0
        for member in members:
            if member.id in {ctx.author.id, ctx.guild.owner_id, ctx.guild.me.id}:
                continue
            if not await self._ensure_targetable(ctx, member):
                continue
            if await self._ban_member(
                ctx, member, reason=reason, action="ban", respond=False,
            ):
                banned += 1
        return await ctx.success(f"Banned **{banned}** recent member(s)")

    @command(
        name="talk",
        description="Toggle a channel to text for a role",
        example=",talk @Members  or  ,talk @Members #general",
    )
    @has_permissions(manage_channels=True)
    async def talk(
        self,
        ctx,
        role: discord.Role,
        channel: discord.TextChannel = None,
    ):
        """toggle channel text for role (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, discord.TextChannel):
            return await ctx.warn("This command only works on **text channels**")
        overwrite = channel.overwrites_for(role)
        if overwrite.send_messages is False:
            overwrite.send_messages = True
            state = "enabled"
        else:
            overwrite.send_messages = False
            state = "disabled"
        await channel.set_permissions(role, overwrite=overwrite, reason=f"talk by {ctx.author}")
        return await ctx.success(
            f"Text in {channel.mention} **{state}** for {role.mention}"
        )

    async def _parse_hide_args(
        self,
        ctx,
        args: str | None,
    ) -> tuple[list[discord.abc.GuildChannel], list[discord.Role | discord.Member], bool]:
        """Parse hide/unhide args into (channels, targets, used_all)."""
        all_channels = False
        channels: list[discord.abc.GuildChannel] = []
        targets: list[discord.Role | discord.Member] = []
        seen_channels: set[int] = set()
        seen_targets: set[int] = set()

        converters = (
            commands.RoleConverter(),
            commands.MemberConverter(),
            commands.GuildChannelConverter(),
        )

        for token in (args or "").split():
            if token.lower() in {"all", "*", "everywhere"}:
                all_channels = True
                continue
            converted = None
            for converter in converters:
                try:
                    converted = await converter.convert(ctx, token)
                except CommandError:
                    continue
                break
            if isinstance(converted, (discord.Role, discord.Member)):
                if converted.id not in seen_targets:
                    seen_targets.add(converted.id)
                    targets.append(converted)
            elif isinstance(converted, discord.abc.GuildChannel):
                if converted.id not in seen_channels:
                    seen_channels.add(converted.id)
                    channels.append(converted)

        if all_channels:
            channels = list(ctx.guild.channels)
        if not channels:
            channels = [ctx.channel]
        return channels, targets, all_channels

    def _default_hide_targets(self, guild: discord.Guild) -> list[discord.Role]:
        """Everyone plus every role that lacks the administrator permission."""
        targets: list[discord.Role] = [guild.default_role]
        for role in guild.roles:
            if role.is_default():
                continue
            if role.permissions.administrator:
                continue
            targets.append(role)
        return targets

    async def _apply_hide_state(
        self,
        ctx,
        channels: list[discord.abc.GuildChannel],
        targets: list[discord.Role | discord.Member],
        *,
        hidden: bool,
    ) -> int:
        action = "hide" if hidden else "unhide"
        applied = 0
        for channel in channels:
            for target in targets:
                overwrite = channel.overwrites_for(target)
                overwrite.view_channel = hidden
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    await channel.set_permissions(
                        target,
                        overwrite=overwrite,
                        reason=f"{action} by {ctx.author}",
                    )
                    applied += 1
        return applied

    async def _toggle_hide(
        self,
        ctx,
        args: str | None,
        *,
        hidden: bool,
    ):
        channels, targets, used_all = await self._parse_hide_args(ctx, args)
        defaulted = not targets
        if not targets:
            targets = self._default_hide_targets(ctx.guild)

        applied = await self._apply_hide_state(ctx, channels, targets, hidden=hidden)
        if not applied:
            return await ctx.warn("No channel permissions could be updated")

        action = "Hid" if hidden else "Unhid"
        if used_all:
            channel_label = "all channels"
        elif len(channels) == 1:
            channel_label = channels[0].mention
        else:
            channel_label = f"**{len(channels)}** channels"

        if defaulted:
            target_label = f"everyone and **{len(targets)}** non-admin role(s)"
        elif len(targets) == 1:
            target_label = targets[0].mention
        else:
            target_label = ", ".join(target.mention for target in targets)

        return await ctx.success(f"{action} {channel_label} from {target_label}")

    @command(
        name="unhide",
        description="Unhide a channel (or all channels) from everyone or from specific roles/members",
        usage="[channel|all] [role/user...]",
        example=",unhide  |  ,unhide all  |  ,unhide @role  |  ,unhide #general @role @user",
    )
    @has_permissions(manage_channels=True)
    async def unhide(self, ctx, *, args: str = None):
        """unhide channel(s) from everyone or specific roles/members"""
        return await self._toggle_hide(ctx, args, hidden=False)

    @command(
        name="hide",
        description="Hide a channel (or all channels) from everyone or from specific roles/members",
        usage="[channel|all] [role/user...]",
        example=",hide  |  ,hide all  |  ,hide @role  |  ,hide #general @role @user",
    )
    @has_permissions(manage_channels=True)
    async def hide(self, ctx, *, args: str = None):
        """hide channel(s) from everyone or specific roles/members"""
        return await self._toggle_hide(ctx, args, hidden=True)

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

            jail_config = await self._ensure_jail_ready(ctx)
            jail_role_id = jail_config["jail_role_id"] if jail_config else None

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
                    overwrites_jail[jail_role] = discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                    )

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
            await self.bot.db.set_security_log_channels(
                ctx.guild.id,
                antinuke_channel_id=antinuke_ch.id,
                antiraid_channel_id=antiraid_ch.id,
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
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove the **moderation system** setup? "
            "This **deletes** the `logs` and `jail` categories and their channels "
            "and clears the modlog configuration. **This cannot be undone.**"
        )
        if not ok:
            return await ctx.warn("Moderation unsetup **cancelled**")

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
        name="setupjail",
        description="Sets up the jail role, channel, and permissions",
    )
    @has_permissions(manage_guild=True, manage_channels=True)
    async def setupjail(self, ctx):
        """setup jail system"""
        async with ctx.typing():
            row = await self._ensure_jail_ready(ctx)
            if not row:
                return await ctx.warn("Failed to set up jail.")
        embed = build_modlog_embed(
            color=self.color,
            action="jail setup",
            target_label=row["jail_channel"].mention,
            moderator_label=ctx.author.mention,
            reason="Jail role and channel configured",
            extra=f"**Role** : {row['jail_role'].mention}",
        )
        embed.title = "Jail Setup Complete"
        await ctx.send(embed=embed)

    @command(
        name="unsetupjail",
        aliases=["resetjail"],
        description="Remove the jail system setup (channel, role and permissions)",
    )
    @has_permissions(manage_guild=True, manage_channels=True, manage_roles=True)
    async def unsetupjail(self, ctx):
        """remove jail system setup"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove the **jail system**? "
            "This **deletes** the jail channel/category and the `Jailed` role. "
            "**This cannot be undone.**"
        )
        if not ok:
            return await ctx.warn("Jail unsetup **cancelled**")

        async with ctx.typing():
            removed = []

            row = await self.db.fetchrow(
                "SELECT jail_channel_id, jail_role_id FROM server_settings WHERE guild_id = $1",
                ctx.guild.id,
            )
            configured_channel_id = (
                int(row["jail_channel_id"]) if row and row["jail_channel_id"] else None
            )
            configured_role_id = (
                int(row["jail_role_id"]) if row and row["jail_role_id"] else None
            )

            jail_cat = discord.utils.get(ctx.guild.categories, name="jail")
            if jail_cat:
                for ch in list(jail_cat.channels):
                    try:
                        await ch.delete(reason="Jail unsetup")
                        removed.append(f"#{ch.name}")
                    except discord.HTTPException:
                        pass
                try:
                    await jail_cat.delete(reason="Jail unsetup")
                    removed.append("Category: jail")
                except discord.HTTPException:
                    pass
            else:
                channel = (
                    ctx.guild.get_channel(configured_channel_id)
                    if configured_channel_id
                    else None
                )
                if channel:
                    try:
                        await channel.delete(reason="Jail unsetup")
                        removed.append(f"#{channel.name}")
                    except discord.HTTPException:
                        pass

            role = (
                ctx.guild.get_role(configured_role_id)
                if configured_role_id
                else None
            )
            if role is None:
                role = discord.utils.get(ctx.guild.roles, name="Jailed")
            if role:
                try:
                    await role.delete(reason="Jail unsetup")
                    removed.append(f"@{role.name}")
                except discord.HTTPException:
                    pass

            await self.db.set_server_settings(
                ctx.guild.id,
                jail_channel_id=None,
                jail_role_id=None,
            )

        if removed:
            await ctx.success(
                f"Removed: {', '.join(removed)}\n"
                f"Use `{ctx.clean_prefix}setupjail` to recreate them."
            )
        else:
            await ctx.warn("No jail setup found to remove.")

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

        embed = panel_embed(
            color=self.bot.color,
            title="Mute Setup Complete",
            lines=[
                label_line("Text Mute", muted_role.mention),
                label_line("Image Mute", imuted_role.mention),
                label_line("Reaction Mute", rmuted_role.mention),
                "Permissions have been applied to all text channels.",
            ],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="unsetupmute",
        aliases=["resetmute"],
        description="Remove the mute system setup (muted roles and permissions)",
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def unsetupmute(self, ctx):
        """remove mute system setup"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove the **mute system**? "
            "This **deletes** the `Muted`, `Image Muted` and `Reaction Muted` roles "
            "and clears the mute configuration. **This cannot be undone.**"
        )
        if not ok:
            return await ctx.warn("Mute unsetup **cancelled**")

        async with ctx.typing():
            removed = []

            row = await self.db.fetchrow(
                "SELECT muted_role_id, imuted_role_id, rmuted_role_id FROM server_settings WHERE guild_id = $1",
                ctx.guild.id,
            )
            configured = {}
            for key in ("muted_role_id", "imuted_role_id", "rmuted_role_id"):
                if row and row[key]:
                    configured[key] = int(row[key])

            for key, name in (
                ("muted_role_id", "Muted"),
                ("imuted_role_id", "Image Muted"),
                ("rmuted_role_id", "Reaction Muted"),
            ):
                role = (
                    ctx.guild.get_role(configured[key])
                    if key in configured
                    else None
                )
                if role is None:
                    role = discord.utils.get(ctx.guild.roles, name=name)
                if role:
                    try:
                        await role.delete(reason="Mute unsetup")
                        removed.append(f"@{role.name}")
                    except discord.HTTPException:
                        pass

            await self.db.set_server_settings(
                ctx.guild.id,
                muted_role_id=None,
                imuted_role_id=None,
                rmuted_role_id=None,
            )

        if removed:
            await ctx.success(
                f"Removed: {', '.join(removed)}\n"
                f"Use `{ctx.clean_prefix}setupmute` to recreate them."
            )
        else:
            await ctx.warn("No mute setup found to remove.")

    @command(
        name="rename",
        description="Assigns the mentioned user a new nickname in the guild",
    )
    @has_permissions(manage_nicknames=True)
    async def rename(self, ctx, member: discord.Member, *, newnick: str):
        """rename a member"""
        if not await self._ensure_targetable(ctx, member):
            return
        try:
            await member.edit(
                nick=newnick[:32],
                reason=f"rename by {ctx.author}",
            )
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to rename this member")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to rename member: {e}")
        return await ctx.success(f"Renamed **{member}** to **{newnick[:32]}**")

    @command(
        name="raid",
        description="Remove all members that joined in the time provided in the event of a raid",
    )
    @has_permissions(ban_members=True, kick_members=True)
    async def raid(self, ctx, time: str, action: str, *, reason: str | None = None):
        """raid mode"""
        seconds = self._parse_duration_seconds(time)
        if not seconds:
            return await ctx.warn("Provide a valid time like `30m`, `2h`, or `1d`")
        action = action.lower().strip()
        if action not in {"ban", "kick"}:
            return await ctx.warn("Action must be **ban** or **kick**")

        cutoff = discord.utils.utcnow() - timedelta(seconds=seconds)
        targets = [
            m for m in ctx.guild.members
            if not m.bot
            and m.joined_at
            and m.joined_at >= cutoff
            and m.id not in {ctx.author.id, ctx.guild.owner_id, ctx.guild.me.id}
        ]
        if not targets:
            return await ctx.warn("No members joined in that window")

        affected = 0
        for member in targets:
            if not await self._ensure_targetable(ctx, member):
                continue
            if action == "ban":
                if await self._ban_member(
                    ctx, member, reason=reason, action="ban", respond=False,
                ):
                    affected += 1
            else:
                case_id = await self._create_case(
                    ctx, action="kick", target_id=member.id, reason=reason,
                )
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    await member.kick(reason=self._audit_reason(ctx, reason))
                    await self._send_modlog(
                        ctx, action="kick", target=member, case_id=case_id, reason=reason,
                    )
                    affected += 1
        return await ctx.success(
            f"**{action.title()}ed** **{affected}** member(s) who joined in the last **{self._format_duration(seconds)}**"
        )

    @command(
        name="topic",
        description="Change the current channel topic",
    )
    @has_permissions(manage_channels=True)
    async def topic(self, ctx, *, text: str):
        """change channel topic"""
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.warn("This command only works in **text channels**")
        await ctx.channel.edit(topic=text[:1024], reason=f"topic by {ctx.author}")
        return await ctx.success("Updated this channel's **topic**")

    @command(
        name="naughty",
        aliases=["nsfw"],
        usage="[duration] [channel]",
        example="30s  or  1d #channel",
        description="Toggle NSFW on a channel (indefinitely or for a duration)",
    )
    @has_permissions(manage_channels=True)
    async def naughty(self, ctx, duration: str = None, channel: discord.TextChannel = None):
        """toggle nsfw on a channel, optionally timed.

        No duration → indefinite toggle until run again.
        With duration (e.g. 20s, 1d) → flip now, auto-revert after that time.
        Running again while timed cancels the pending revert and toggles immediately.
        """
        
        if duration is not None and channel is None:
            seconds = self._parse_duration_seconds(duration)
            if seconds is None:
                try:
                    channel = await commands.TextChannelConverter().convert(ctx, duration)
                    duration = None
                    seconds = None
                except commands.BadArgument:
                    return await ctx.warn(
                        f"Invalid duration `{duration}`. Use e.g. `30s`, `5m`, `1h`, `1d`, `1w`"
                    )
        else:
            seconds = self._parse_duration_seconds(duration) if duration else None
            if duration and seconds is None:
                return await ctx.warn(
                    f"Invalid duration `{duration}`. Use e.g. `30s`, `5m`, `1h`, `1d`, `1w`"
                )

        channel = channel or ctx.channel
        if not isinstance(channel, discord.TextChannel):
            return await ctx.warn("This command only works on **text channels**")

        if not channel.permissions_for(ctx.guild.me).manage_channels:
            return await ctx.warn("I don't have **Manage Channels** for that channel")

        
        pending = self._naughty_tasks.pop(channel.id, None)
        if pending is not None and not pending.done():
            pending.cancel()

        was_nsfw = channel.nsfw
        target = not was_nsfw
        action = "enabled" if target else "disabled"
        reason = f"naughty by {ctx.author}"

        try:
            await channel.edit(nsfw=target, reason=reason)
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to update channel: {e}")

        if seconds and seconds > 0:
            label = self._format_duration(seconds)
            await ctx.success(
                f"{action.title()} NSFW on {channel.mention} for **{label}** "
                f"(will revert to {'NSFW' if was_nsfw else 'SFW'} afterwards)"
            )
            guild_id = ctx.guild.id
            channel_id = channel.id
            revert_to = was_nsfw

            async def _revert() -> None:
                try:
                    await asyncio.sleep(seconds)
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        return
                    ch = guild.get_channel(channel_id)
                    if ch and isinstance(ch, discord.TextChannel) and ch.nsfw != revert_to:
                        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                            await ch.edit(nsfw=revert_to, reason="naughty expired")
                except asyncio.CancelledError:
                    return
                finally:
                    current = self._naughty_tasks.get(channel_id)
                    if current is asyncio.current_task():
                        self._naughty_tasks.pop(channel_id, None)

            self._naughty_tasks[channel_id] = asyncio.create_task(_revert())
        else:
            await ctx.success(f"{action.title()} NSFW on {channel.mention} **indefinitely**")

    @command(
        name="permissions",
        description="Check permissions for member or myself",
    )
    @has_permissions(manage_roles=True, manage_channels=True)
    async def permissions(
        self,
        ctx,
        member: discord.Member,
        channel: discord.abc.GuildChannel | None = None,
    ):
        """check permissions"""
        channel = channel or ctx.channel
        perms = channel.permissions_for(member)
        keys = (
            "view_channel", "send_messages", "read_message_history", "attach_files",
            "embed_links", "add_reactions", "manage_messages", "manage_channels",
            "manage_roles", "ban_members", "kick_members", "moderate_members",
        )
        lines = [
            label_line(key.replace("_", " ").title(), "yes" if getattr(perms, key) else "no")
            for key in keys
        ]
        embed = panel_embed(
            title=f"Permissions - {member.display_name}",
            color=self.color,
            lines=lines,
            footer=channel.mention,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @tasks.loop(seconds=30)
    async def temprole_watcher(self) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        for entry in await self.db.fetch_due_temproles():
            guild = self.bot.get_guild(int(entry["guild_id"]))
            if guild is None:
                continue
            member = guild.get_member(int(entry["user_id"]))
            role = guild.get_role(int(entry["role_id"]))
            if member and role and role in member.roles:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await member.remove_roles(role, reason="temprole expired")
            await self.db.remove_temprole(
                int(entry["guild_id"]),
                int(entry["user_id"]),
                int(entry["role_id"]),
            )

from discord.ext import commands

from core.discord.mixin import _Meta

from .extended.nuke import Nuke
from .extended.thread import Thread
from .extended.lockdown import Lockdown
from .extended.remind import Remind
from .extended.role import Role
from .extended.purge import Purge
from .extended.history import History
from .extended.proof import Proof
from .extended.notes import Notes
from .extended.slowmode import Slowmode
from .extended.revokefiles import Revokefiles
from .extended.restrictcommand import Restrictcommand
from .extended.stickyrole import Stickyrole
from .extended.forcenickname import Forcenickname
from .extended.honeypot import Honeypot
from .extended.honeypot.events import HoneypotEvents

class Moderation(
    ModerationCommands,
    Nuke,
    Thread,
    Lockdown,
    Remind,
    Role,
    Purge,
    History,
    Proof,
    Notes,
    Slowmode,
    Revokefiles,
    Restrictcommand,
    Stickyrole,
    Forcenickname,
    Honeypot,
    HoneypotEvents,
    commands.Cog,
    metaclass=_Meta,
):
    """main moderation extension - all subcommands combined"""

async def setup(bot) -> None:
    """load moderation extension"""
    from .events import ModerationEvents

    await bot.add_cog(Moderation(bot))
    await bot.add_cog(ModerationEvents(bot))
