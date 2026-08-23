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
    send_c2_embed,
    send_invoke_dm,
    send_invoke_response,
)

from core.managers.permissions import has_permissions

from core.discord.views.embed import panel_embed, reply_embed
from core.tools.human.time import human_date
from ext.moderation.settings import Settings
from ext.server.extended.invoke import register_invoke_subgroup

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
        self.message: discord.Message | None = None

        self.clear_items()
        approve = discord.ui.Button(label="Approve", style=discord.ButtonStyle.primary)
        decline = discord.ui.Button(label="Decline", style=discord.ButtonStyle.danger)
        approve.callback = self._approve
        decline.callback = self._decline
        self.add_item(approve)
        self.add_item(decline)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                f"Only {self.ctx.author.mention} can use this.",
                ephemeral=True,
            )
            return False
        return True

    async def _approve(self, interaction: discord.Interaction):
        self.value = True
        await interaction.response.defer()
        self.stop()

    async def _decline(self, interaction: discord.Interaction):
        self.value = False
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.value = False
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()

    async def prompt(self) -> bool:
        from core.discord.views.confirm import _build_confirm_layout
        message = (
            f"Are you sure you want to **{self._action}** {self.member.mention}?\n"
            f"They are currently boosting the server."
        )
        layout = _build_confirm_layout(message)
        self.message = await self.ctx.send(view=layout)
        with contextlib.suppress(discord.HTTPException, Exception):
            await self.message.edit(view=self)
        await self.wait()
        if not self.value:
            from core.discord.views.confirm import ConfirmView
            cancel_view = ConfirmView(self.ctx)
            cancel_view.value = False
            if self.message is not None:
                with contextlib.suppress(Exception):
                    await self.message.edit(
                        embed=cancel_view._cancel_warn_embed("Cancelled"),
                        view=None,
                    )
                    await asyncio.sleep(5)
        with contextlib.suppress(discord.HTTPException):
            if self.message is not None:
                await self.message.delete()
        return bool(self.value)

class ModerationCommands(Package):
    """standalone moderation commands"""

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._unbanall_tasks: dict[int, asyncio.Task] = {}
        self._naughty_tasks: dict[int, asyncio.Task] = {}

    async def _set_invoke(self, ctx, action: str, target: str, code: str) -> None:
        column = "dm_code" if target == "dm" else "message_code"
        await Settings.set_invoke(self.bot.db, ctx.guild.id, action, column, code)

    async def _set_invoke_enabled(self, ctx, action: str, target: str, enabled: bool) -> None:
        column = "dm_enabled" if target == "dm" else "message_enabled"
        await self.db.execute(
            f"""INSERT INTO invocation (guild_id, command, {column})
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, command)
                DO UPDATE SET {column} = excluded.{column}""",
            ctx.guild.id, action, enabled,
        )

    async def _view_invoke(self, ctx, action: str, target: str):
        column = "dm_code" if target == "dm" else "message_code"
        from core.tools.moderation_logs import DEFAULT_INVOKE_DM, DEFAULT_INVOKE_RESPONSE
        msg = await self.db.fetchval(
            f"""SELECT {column} FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, action,
        )
        if not msg:
            defaults = DEFAULT_INVOKE_DM if target == "dm" else DEFAULT_INVOKE_RESPONSE
            msg = defaults.get(action)
        if not msg:
            from discord.ext.commands import CommandError
            raise CommandError(f"no {action} {('DM' if target == 'dm' else 'response')} set")
        return await self.bot.send_embed(
            ctx.channel, msg, user=ctx.author, moderator=ctx.author,
        )

    async def cog_load(self) -> None:
        if self.db.pool is not None:
            self.tempban_watcher.start()
            self.temprole_watcher.start()
        await super().cog_load()

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
        await super().cog_unload()
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

    async def _ensure_targetable(self, ctx, member: discord.Member | None, user: discord.User | None = None) -> bool:
        """Check if a target can be moderated. Returns True if OK, False if blocked."""
        from core.tools.hierarchy import ensure_member_hierarchy
        from discord.ext.commands import CommandError as _CmdErr

        if ctx.guild is None:
            await ctx.warn("Server only\n> -# **this command can only be used in a server**")
            return False
        if member is None:
            return True
        if member.id == ctx.guild.owner_id:
            await ctx.warn(f"you **can't** {ctx.command.name} the **guild owner**!")
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        try:
            await ensure_member_hierarchy(ctx, member, allow_self=False)
        except _CmdErr as e:
            await ctx.warn(f"{e}")
            return False
        return True

    async def _check_not_owner(self, ctx, member: discord.Member) -> bool:
        """Check if target is the guild owner. Returns True if OK, False if blocked."""
        if ctx.guild is None:
            return True
        if member.id == ctx.guild.owner_id:
            await ctx.warn(f"you **can't** {ctx.command.name} the **guild owner**!")
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
            color=None,
            action=action,
            target_label=target_label,
            moderator_label=ctx.author.mention,
            reason=self._default_reason(reason),
            case_id=case_id,
            extra=extra,
        )
        await send_c2_embed(channel, embed)

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

    def _format_case_line(self, row, user_cache: dict | None = None) -> str:
        cache = user_cache or {}
        moderator_id = row.get("moderator_id")

        if moderator_id and moderator_id in cache:
            moderator = cache[moderator_id]
        elif moderator_id:
            moderator = f"`{moderator_id}`"
        else:
            moderator = "unknown"

        when = human_date(row.get("created_at"), fallback="unknown")
        reason = row.get("reason") or "no reason provided"

        lines = [
            f"**Case #{row['case_id']}** - `{row['action']}`",
            f"-# **moderator**: {moderator}",
            f"-# **when**: {when}",
            f"-# **reason**: {reason}",
        ]

        edited_at = row.get("edited_at")
        edited_by = row.get("edited_by")
        if edited_at:
            edited_when = human_date(edited_at, fallback="unknown")
            editor = cache.get(edited_by, f"`{edited_by}`") if edited_by else "unknown"
            lines.append(f"-# **edited**: {edited_when} by {editor}")

        return "\n".join(lines)


    def _json_module_status(self, val) -> bool:
        import json
        if val is None:
            return False
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                return False
        if isinstance(val, dict):
            return bool(val.get("status"))
        return False

    async def _antinuke_enabled(self, guild_id: int) -> bool:
        try:
            cog = self.bot.get_cog("Antinuke")
            if cog is not None and hasattr(cog, "_guild_config"):
                cfg = await cog._guild_config(guild_id)
                return bool(cfg.enabled_modules())
        except Exception:
            pass
        try:
            row = await self.db.fetchrow(
                "SELECT ban, kick, channel, role, webhook, emoji, vanity, botadd FROM antinuke WHERE guild_id = $1",
                guild_id,
            )
        except Exception:
            return False
        if not row:
            return False
        for key in ("ban", "kick", "channel", "role", "webhook", "emoji", "vanity", "botadd"):
            try:
                val = row[key]
            except Exception:
                val = row.get(key) if hasattr(row, "get") else None
            if self._json_module_status(val):
                return True
        return False

    async def _is_antinuke_admin(self, ctx) -> bool:
        if ctx.guild is None:
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        try:
            if hasattr(self.db, "is_antinuke_admin"):
                return bool(await self.db.is_antinuke_admin(ctx.guild.id, ctx.author.id))
        except Exception:
            pass
        try:
            row = await self.db.fetchrow(
                "SELECT admins FROM antinuke WHERE guild_id = $1",
                ctx.guild.id,
            )
            if row:
                admins = row["admins"] if hasattr(row, "keys") else row[0]
                return ctx.author.id in list(admins or [])
        except Exception:
            pass
        return False

    async def _require_antinuke_for_hardban(self, ctx) -> bool:
        enabled = await self._antinuke_enabled(ctx.guild.id)
        if not enabled:
            await ctx.warn(
                "antinuke isn't enabled in this guild\n"
                "> -# **enable it using** `antinuke setup`"
            )
            return False
        if not await self._is_antinuke_admin(ctx):
            await ctx.warn(
                "You are missing permissions to use this punishment\n"
                "> -# **Permission Needed: Antinuke Admin**"
            )
            return False
        return True

    async def _action_c2(self, ctx, message: str):
        """Colorless C2 confirm for mod actions (jailed / banned / etc.)."""
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        import contextlib
        text = (message or "").strip()
        if not text:
            return None
        container = _ui.Container()
        for attr in ("accent_color", "accent_colour", "color", "colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(text))
        view = layout_from_items([container], timeout=None)
        return await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())


    def _action_line(self, verb: str, target, *, reason: str | None = None, extra: str | None = None) -> str:
        mention = getattr(target, "mention", None) or f"**{target}**"
        lines = [f"> -# **{verb}** {mention}"]
        if reason is not None:
            lines.append(f"> -# **reason:** {self._default_reason(reason)}")
        if extra:
            lines.append(f"> -# {extra}")
        return chr(10).join(lines)


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
            await ctx.warn("Action cancelled\n> -# **booster confirmation declined**")
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
            purge = f" (purged {delete_days}d)" if delete_days else ""
            duration = f" for {duration_label}" if duration_label else ""
        return await ctx.success(
            f"{action.title()}ed **{target_display}**{duration}{purge}\n> -# **reason:** {self._default_reason(reason)}"
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
            return await ctx.warn("Action cancelled\n> -# **booster confirmation declined**")

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
        return await self._action_c2(ctx, f"Tempbanned **{target_display}** for {duration_label}\n> -# **reason:** {self._default_reason(reason)}")

    @group(
        name="tempban",
        usage="(duration) (member) <reason>",
        example="3h @member spamming",
        description="temporarily ban a member",
        invoke_without_command=True,
    )
    @has_permissions(ban_members=True)
    async def tempban(self, ctx):
        """temporarily ban a member"""
        parsed = await parse_moderation_args(ctx, command_names=("tempban",), allow_duration=True)
        if not parsed.duration_seconds:
            raise CommandError("you must provide a duration like `3h`, `2d`, `1w`, or `1y`")
        await self._run_tempban(ctx, parsed)

    @tempban.group(
        name="invoke",
        description="customize tempban punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def tempban_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @tempban_invoke.command(name="on", description="enable tempban response")
    @has_permissions(manage_guild=True)
    async def tempban_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "tempban", "message", True)
        return await ctx.success("tempban response **enabled**")

    @tempban_invoke.command(name="off", description="disable tempban response")
    @has_permissions(manage_guild=True)
    async def tempban_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "tempban", "message", False)
        return await ctx.success("tempban response **disabled**")

    @tempban_invoke.group(name="dm", description="customize tempban dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def tempban_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "tempban", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "tempban", "dm", message)
        return await ctx.success("tempban DM updated")

    @tempban_invoke_dm.command(name="on", description="enable tempban dm")
    @has_permissions(manage_guild=True)
    async def tempban_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "tempban", "dm", True)
        return await ctx.success("tempban DM **enabled**")

    @tempban_invoke_dm.command(name="off", description="disable tempban dm")
    @has_permissions(manage_guild=True)
    async def tempban_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "tempban", "dm", False)
        return await ctx.success("tempban DM **disabled**")

    @tempban_invoke_dm.command(name="view", description="view tempban dm")
    @has_permissions(manage_guild=True)
    async def tempban_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "tempban", "dm")

    @tempban_invoke.group(name="message", aliases=["msg"], description="customize tempban response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def tempban_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "tempban", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "tempban", "message", message)
        return await ctx.success("tempban response updated")

    @tempban_invoke_message.command(name="view", description="view tempban response")
    @has_permissions(manage_guild=True)
    async def tempban_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "tempban", "message")

    @group(
        name="warn",
        description="warns the mentioned user and private messages them the warning",
        invoke_without_command=True,
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
        return await self._action_c2(ctx, f"Warned **{member}**\n> -# **reason:** {self._default_reason(reason)}")

    @warn.group(
        name="invoke",
        description="customize warn punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def warn_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @warn_invoke.command(name="on", description="enable warn response")
    @has_permissions(manage_guild=True)
    async def warn_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "warn", "message", True)
        return await ctx.success("warn response **enabled**")

    @warn_invoke.command(name="off", description="disable warn response")
    @has_permissions(manage_guild=True)
    async def warn_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "warn", "message", False)
        return await ctx.success("warn response **disabled**")

    @warn_invoke.group(name="dm", description="customize warn dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def warn_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "warn", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "warn", "dm", message)
        return await ctx.success("warn DM updated")

    @warn_invoke_dm.command(name="on", description="enable warn dm")
    @has_permissions(manage_guild=True)
    async def warn_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "warn", "dm", True)
        return await ctx.success("warn DM **enabled**")

    @warn_invoke_dm.command(name="off", description="disable warn dm")
    @has_permissions(manage_guild=True)
    async def warn_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "warn", "dm", False)
        return await ctx.success("warn DM **disabled**")

    @warn_invoke_dm.command(name="view", description="view warn dm")
    @has_permissions(manage_guild=True)
    async def warn_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "warn", "dm")

    @warn_invoke.group(name="message", aliases=["msg"], description="customize warn response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def warn_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "warn", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "warn", "message", message)
        return await ctx.success("warn response updated")

    @warn_invoke_message.command(name="view", description="view warn response")
    @has_permissions(manage_guild=True)
    async def warn_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "warn", "message")

    @command(
        name="moveall",
        description="move all members in your voice channel to another channel",
    )
    @has_permissions(move_members=True)
    async def moveall(self, ctx, channel: discord.VoiceChannel):
        """move all members to another channel"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.warn("Not in voice\n> -# **must be in a voice channel**")

        source = ctx.author.voice.channel

        if source.id == channel.id:
            return await ctx.warn("Invalid target\n> -# **source and destination can't be the same**")

        if not ctx.guild.me.guild_permissions.move_members:
            return await ctx.warn("Missing permissions\n> -# **need Move Members permission**")

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
        description="remove all roles with dangerous permissions from a member",
    )
    @has_permissions(manage_roles=True)
    async def stripstaff(self, ctx, *, member: discord.Member):
        """strip dangerous/staff roles from member"""
        if member.id == ctx.author.id:
            return await ctx.warn("Invalid target\n> -# **can't strip yourself**")

        if member.id == ctx.guild.owner_id:
            return await ctx.warn("Invalid target\n> -# **can't strip server owner**")

        if ctx.author.top_role <= member.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.warn("Role hierarchy\n> -# **your top role must be higher**")

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
            return await ctx.warn(f"No dangerous roles\n> -# **{member.mention} has none to strip**")

        return await self._action_c2(ctx, f"Stripped **{len(removed)}** dangerous roles from {member.mention}\n> -# **{', '.join(removed)}**")

    @group(
        name="jail",
        usage="[duration] (member) <reason>",
        example="2d @member spamming",
        description="jails the mentioned user",
        invoke_without_command=True,
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
            return await ctx.warn(f"Jail setup failed\n> -# **try** {ctx.cmd('setupjail')}")

        jail_role = row["jail_role"]
        jail_channel = row["jail_channel"]

        existing = await self.db.fetchrow(
            "SELECT 1 FROM jailed WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, member.id,
        )
        if existing:
            return await ctx.warn(f"Already jailed\n> -# **{member}** is already in jail")

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
            return await ctx.warn("Missing permissions\n> -# **can't manage member roles**")
        except discord.HTTPException as e:
            return await ctx.warn(f"Role update failed\n> -# **{e}**")

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
            from discord import ui as _ui
            from core.discord.ctx import layout_from_items
            container = _ui.Container()
            for attr in ("accent_color", "accent_colour", "color", "colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(
                _ui.TextDisplay(
                    "you have been **jailed**\n> -# please **wait** for a staff to address the situation"
                )
            )
            with contextlib.suppress(Exception):
                await jail_channel.send(
                    content=member.mention,
                    view=layout_from_items([container], timeout=None),
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

        if await self._invoke_response(ctx, "jail", user=member, reason=reason, case_id=case_id):
            return
        return await self._action_c2(
            ctx,
            self._action_line("Jailed", member, reason=reason, extra=f"in {jail_channel.mention}"),
        )

    @jail.group(
        name="invoke",
        description="customize jail punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def jail_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @jail_invoke.command(name="on", description="enable jail response")
    @has_permissions(manage_guild=True)
    async def jail_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "jail", "message", True)
        return await ctx.success("jail response **enabled**")

    @jail_invoke.command(name="off", description="disable jail response")
    @has_permissions(manage_guild=True)
    async def jail_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "jail", "message", False)
        return await ctx.success("jail response **disabled**")

    @jail_invoke.group(name="dm", description="customize jail dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def jail_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "jail", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "jail", "dm", message)
        return await ctx.success("jail DM updated")

    @jail_invoke_dm.command(name="on", description="enable jail dm")
    @has_permissions(manage_guild=True)
    async def jail_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "jail", "dm", True)
        return await ctx.success("jail DM **enabled**")

    @jail_invoke_dm.command(name="off", description="disable jail dm")
    @has_permissions(manage_guild=True)
    async def jail_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "jail", "dm", False)
        return await ctx.success("jail DM **disabled**")

    @jail_invoke_dm.command(name="view", description="view jail dm")
    @has_permissions(manage_guild=True)
    async def jail_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "jail", "dm")

    @jail_invoke.group(name="message", aliases=["msg"], description="customize jail response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def jail_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "jail", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "jail", "message", message)
        return await ctx.success("jail response updated")

    @jail_invoke_message.command(name="view", description="view jail response")
    @has_permissions(manage_guild=True)
    async def jail_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "jail", "message")

    @group(
        name="unjail",
        description="unjails the mentioned user",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def unjail(self, ctx, member: discord.Member, *, reason=None):
        """unjail a member"""
        if not await self._check_not_owner(ctx, member):
            return
        row = await self.db.fetchrow(
            "SELECT * FROM jailed WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, member.id,
        )
        if not row:
            return await ctx.warn(f"Not jailed\n> -# **{member}** is not in jail")

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
            return await ctx.warn("Missing permissions\n> -# **can't manage member roles**")
        except discord.HTTPException as e:
            return await ctx.warn(f"Role restore failed\n> -# **{e}**")

        
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
        return await self._action_c2(ctx, f"Unjailed **{member}**\n> -# **reason:** {self._default_reason(reason)}")

    @unjail.group(name="invoke", description="customize unjail messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def unjail_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @unjail_invoke.command(name="on", description="enable unjail response")
    @has_permissions(manage_guild=True)
    async def unjail_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "unjail", "message", True)
        return await ctx.success("unjail response **enabled**")

    @unjail_invoke.command(name="off", description="disable unjail response")
    @has_permissions(manage_guild=True)
    async def unjail_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "unjail", "message", False)
        return await ctx.success("unjail response **disabled**")

    @unjail_invoke.group(name="dm", description="customize unjail dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def unjail_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "unjail", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "unjail", "dm", message)
        return await ctx.success("unjail DM updated")

    @unjail_invoke_dm.command(name="on", description="enable unjail dm")
    @has_permissions(manage_guild=True)
    async def unjail_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "unjail", "dm", True)
        return await ctx.success("unjail DM **enabled**")

    @unjail_invoke_dm.command(name="off", description="disable unjail dm")
    @has_permissions(manage_guild=True)
    async def unjail_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "unjail", "dm", False)
        return await ctx.success("unjail DM **disabled**")

    @unjail_invoke_dm.command(name="view", description="view unjail dm")
    @has_permissions(manage_guild=True)
    async def unjail_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "unjail", "dm")

    @unjail_invoke.group(name="message", aliases=["msg"], description="customize unjail response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def unjail_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "unjail", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "unjail", "message", message)
        return await ctx.success("unjail response updated")

    @unjail_invoke_message.command(name="view", description="view unjail response")
    @has_permissions(manage_guild=True)
    async def unjail_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "unjail", "message")

    @command(
        name="modstats",
        description="no description given",
    )
    @has_permissions(manage_messages=True)
    async def modstats(self, ctx, member: discord.Member):
        """view moderation stats for a member"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database unavailable\n> -# **could not load mod stats**")
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
        description="view warnings for a member",
    )
    @has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member):
        """view warnings for a member"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database unavailable\n> -# **could not load warnings**")
        rows = await self.db.fetch_modlog_cases_for_user(
            ctx.guild.id, member.id, action="warn", limit=25
        )
        if not rows:
            return await ctx.warn(f"No warnings\n> -# **{member.mention}** has no warnings")
        embed = panel_embed(
            title=f"Warnings - {member}",
            color=self.color,
            lines=[self._format_case_line(row) for row in rows],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @command(
        name="moderationhistory",
        description="view moderation actions from a staff member",
    )
    @has_permissions(manage_messages=True)
    async def moderationhistory(self, ctx, member: discord.Member, command: str | None = None):
        """view moderation history for a staff member"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database unavailable\n> -# **could not load history**")
        rows = await self.db.fetch_modlog_cases_by_moderator(
            ctx.guild.id,
            member.id,
            action=command.lower() if command else None,
            limit=25,
        )
        if not rows:
            return await ctx.warn(f"No actions\n> -# **{member.mention}** has no recorded actions")
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
        description="view a list of every current jailed member",
    )
    @has_permissions(manage_messages=True)
    async def jaillist(self, ctx):
        """list all jailed members"""
        rows = await self.db.fetch(
            "SELECT user_id, moderator_id, reason, jailed_at FROM jailed WHERE guild_id = $1 ORDER BY jailed_at DESC",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No jailed members\n> -# **no members are currently in jail**")

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
        description="view a case log",
    )
    @has_permissions(manage_messages=True)
    async def caselog(self, ctx, case_id: int):
        """view case log"""
        embed = await self._build_case_embed(ctx, case_id)
        if embed is None:
            return await ctx.warn(f"Case not found\n> -# **#{case_id}** does not exist")
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

        seconds = parsed.duration_seconds if parsed.duration_seconds is not None else (28 * 86400)
        if seconds < 60:
            return await ctx.warn("Please provide a **valid duration**\n> -# **minimum timeout is `60 seconds` (e.g. `5m`, `1h`, `1d`)**")
        if seconds > 28 * 86400:
            return await ctx.warn("Please provide a **shorter duration**\n> -# **Discord limits timeouts to `28 days` maximum**")

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
            return await ctx.fail("Missing permissions\n> -# **can't timeout this member**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Timeout failed\n> -# **{e}**")

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
        return await self._action_c2(ctx, f"Timed out **{member}** for {duration_label}\n> -# **reason:** {self._default_reason(reason)}")

    @timeout.command(
        name="list",
        description="view list of timed out members",
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
            return await ctx.warn("No timeouts\n> -# **no members currently timed out**")
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

    @timeout.group(
        name="invoke",
        description="customize timeout punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @timeout_invoke.command(
        name="on",
        description="enable timeout command response messages",
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "timeout", "message", True)
        return await ctx.success("timeout response **enabled**")

    @timeout_invoke.command(
        name="off",
        description="disable timeout command response messages",
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "timeout", "message", False)
        return await ctx.success("timeout response **disabled**")

    @timeout_invoke.group(
        name="dm",
        description="customize timeout direct message",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            converter = EmbedConverter()
            result = await converter.convert(ctx, message)
            await self._set_invoke(ctx, "timeout", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "timeout", "dm", message)
        return await ctx.success("timeout DM updated")

    @timeout_invoke_dm.command(
        name="on",
        description="enable timeout dm notifications",
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "timeout", "dm", True)
        return await ctx.success("timeout DM **enabled**")

    @timeout_invoke_dm.command(
        name="off",
        description="disable timeout dm notifications",
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "timeout", "dm", False)
        return await ctx.success("timeout DM **disabled**")

    @timeout_invoke_dm.command(
        name="view",
        description="view the timeout dm message",
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "timeout", "dm")

    @timeout_invoke.group(
        name="message",
        aliases=["msg"],
        description="customize timeout command response",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            converter = EmbedConverter()
            result = await converter.convert(ctx, message)
            await self._set_invoke(ctx, "timeout", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "timeout", "message", message)
        return await ctx.success("timeout response updated")

    @timeout_invoke_message.command(
        name="view",
        description="view the timeout response message",
    )
    @has_permissions(manage_guild=True)
    async def timeout_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "timeout", "message")

    @group(
        name="untimeout",
        aliases=["unmute"],
        description="removes a timeout for a member",
        example=",untimeout @member",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason=None):
        """remove timeout from a member"""
        if not await self._check_not_owner(ctx, member):
            return
        if not member.timed_out_until or member.timed_out_until <= discord.utils.utcnow():
            return await ctx.warn(f"Not timed out\n> -# **{member.mention}** is not timed out")
        case_id = await self._create_case(
            ctx, action="untimeout", target_id=member.id, reason=reason,
        )
        await self._invoke_dm(ctx, member, "untimeout", reason=reason, case_id=case_id)
        try:
            await member.timeout(None, reason=self._audit_reason(ctx, reason))
        except discord.Forbidden:
            return await ctx.fail("Missing permissions\n> -# **can't remove timeout**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Timeout removal failed\n> -# **{e}**")
        await self._send_modlog(
            ctx, action="untimeout", target=member, case_id=case_id, reason=reason,
        )
        if await self._invoke_response(ctx, "untimeout", user=member, reason=reason, case_id=case_id):
            return
        return await self._action_c2(ctx, f"Removed timeout for **{member}**\n> -# **reason:** {self._default_reason(reason)}")

    @untimeout.group(name="invoke", description="customize untimeout messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def untimeout_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @untimeout_invoke.command(name="on", description="enable untimeout response")
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "untimeout", "message", True)
        return await ctx.success("untimeout response **enabled**")

    @untimeout_invoke.command(name="off", description="disable untimeout response")
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "untimeout", "message", False)
        return await ctx.success("untimeout response **disabled**")

    @untimeout_invoke.group(name="dm", description="customize untimeout dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "untimeout", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "untimeout", "dm", message)
        return await ctx.success("untimeout DM updated")

    @untimeout_invoke_dm.command(name="on", description="enable untimeout dm")
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "untimeout", "dm", True)
        return await ctx.success("untimeout DM **enabled**")

    @untimeout_invoke_dm.command(name="off", description="disable untimeout dm")
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "untimeout", "dm", False)
        return await ctx.success("untimeout DM **disabled**")

    @untimeout_invoke_dm.command(name="view", description="view untimeout dm")
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "untimeout", "dm")

    @untimeout_invoke.group(name="message", aliases=["msg"], description="customize untimeout response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "untimeout", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "untimeout", "message", message)
        return await ctx.success("untimeout response updated")

    @untimeout_invoke_message.command(name="view", description="view untimeout response")
    @has_permissions(manage_guild=True)
    async def untimeout_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "untimeout", "message")

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
        row = await Settings.get_mute_role(self.bot.db, ctx.guild.id, role_key)
        if not row or not row.get(role_key):
            setting_name = {"": "muted", "i": "imuted", "r": "rmuted"}.get(mute_type, mute_type)
            return await ctx.warn(
                f"No mute role\n> -# **use** `{ctx.invoke_prefix}settings {setting_name}` to configure"
            )
        role = ctx.guild.get_role(row[role_key])
        if not role:
            return await ctx.warn("Role missing\n> -# **configured mute role no longer exists**")

        role_label = {"": "text-muted", "i": "image-muted", "r": "reaction-muted"}.get(mute_type, mute_type)

        expires_at = None
        seconds = None
        if duration:
            seconds = self._parse_duration_seconds(duration)
            if not seconds:
                return await ctx.warn(f"Invalid duration\n> -# **{duration}** is not valid (examples: 30m, 2h, 7d)")
            expires_at = discord.utils.utcnow() + timedelta(seconds=seconds)

        if role in member.roles:
            return await ctx.warn(f"Already muted\n> -# **{member}** is already {role_label}")

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
        await Settings.insert_mute(
            self.bot.db,
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
            parts.append(f"> -# **Duration: {duration_label}**")
        parts.append(f"> -# **Reason: {self._default_reason(reason)}**")
        return await self._action_c2(ctx, f"\n".join(parts))

    async def _unmute_member(
        self,
        ctx,
        member: discord.Member,
        mute_type: str,
        *,
        reason: str | None = None,
    ):
        if not await self._check_not_owner(ctx, member):
            return
        role_key = f"{mute_type}muted_role_id"
        if mute_type == "":
            role_key = "muted_role_id"
        row = await Settings.get_mute_role(self.bot.db, ctx.guild.id, role_key)
        if not row or not row.get(role_key):
            return await ctx.warn("No mute role\n> -# **no mute role is configured**")

        role = ctx.guild.get_role(row[role_key])
        if role and role in member.roles:
            await member.remove_roles(role, reason=self._audit_reason(ctx, reason))

        await Settings.delete_mute(self.bot.db, ctx.guild.id, member.id, mute_type or "text")

        role_label = {"": "text-muted", "i": "image-muted", "r": "reaction-muted"}.get(mute_type, mute_type)
        if mute_type == "":
            await self._invoke_dm(ctx, member, "unmute", reason=reason)
            if await self._invoke_response(ctx, "unmute", user=member, reason=reason):
                return
        return await ctx.success(f"Un{mute_type if mute_type else 'mute'}d **{member}**\n> -# **reason:** {self._default_reason(reason)}")

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
        if isinstance(target, discord.Member):
            if not await self._check_not_owner(ctx, target):
                return
        if isinstance(target, discord.Role):
            members = [m for m in target.members if not m.bot]
            if not members:
                return await ctx.warn(f"No members\n> -# **no members found with** {target.mention}")
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

    @group(
        name="imagemute",
        aliases=["imute", "imgmute"],
        description="image mute a member or role",
        example=",imagemute @member",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def imagemute(self, ctx, target: str, *, reason: str | None = None):
        """Image mute a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Not found\n> -# **no member or role matching** {target}")
        return await self._apply_special_mute(ctx, resolved, "i", reason=reason)

    @imagemute.group(name="invoke", description="customize imagemute messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def imagemute_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @imagemute_invoke.command(name="on", description="enable imagemute response")
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "imagemute", "message", True)
        return await ctx.success("imagemute response **enabled**")

    @imagemute_invoke.command(name="off", description="disable imagemute response")
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "imagemute", "message", False)
        return await ctx.success("imagemute response **disabled**")

    @imagemute_invoke.group(name="dm", description="customize imagemute dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "imagemute", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "imagemute", "dm", message)
        return await ctx.success("imagemute DM updated")

    @imagemute_invoke_dm.command(name="on", description="enable imagemute dm")
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "imagemute", "dm", True)
        return await ctx.success("imagemute DM **enabled**")

    @imagemute_invoke_dm.command(name="off", description="disable imagemute dm")
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "imagemute", "dm", False)
        return await ctx.success("imagemute DM **disabled**")

    @imagemute_invoke_dm.command(name="view", description="view imagemute dm")
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "imagemute", "dm")

    @imagemute_invoke.group(name="message", aliases=["msg"], description="customize imagemute response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "imagemute", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "imagemute", "message", message)
        return await ctx.success("imagemute response updated")

    @imagemute_invoke_message.command(name="view", description="view imagemute response")
    @has_permissions(manage_guild=True)
    async def imagemute_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "imagemute", "message")

    @group(
        name="imageunmute",
        aliases=["iunmute", "unimagemute"],
        description="remove image mute from a member or role",
        example=",imageunmute @member",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def imageunmute(self, ctx, target: str, *, reason: str | None = None):
        """Remove image mute from a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Not found\n> -# **no member or role matching** {target}")
        return await self._apply_special_mute(
            ctx, resolved, "i", reason=reason, remove=True
        )

    @imageunmute.group(name="invoke", description="customize imageunmute messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @imageunmute_invoke.command(name="on", description="enable imageunmute response")
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "imageunmute", "message", True)
        return await ctx.success("imageunmute response **enabled**")

    @imageunmute_invoke.command(name="off", description="disable imageunmute response")
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "imageunmute", "message", False)
        return await ctx.success("imageunmute response **disabled**")

    @imageunmute_invoke.group(name="dm", description="customize imageunmute dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "imageunmute", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "imageunmute", "dm", message)
        return await ctx.success("imageunmute DM updated")

    @imageunmute_invoke_dm.command(name="on", description="enable imageunmute dm")
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "imageunmute", "dm", True)
        return await ctx.success("imageunmute DM **enabled**")

    @imageunmute_invoke_dm.command(name="off", description="disable imageunmute dm")
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "imageunmute", "dm", False)
        return await ctx.success("imageunmute DM **disabled**")

    @imageunmute_invoke_dm.command(name="view", description="view imageunmute dm")
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "imageunmute", "dm")

    @imageunmute_invoke.group(name="message", aliases=["msg"], description="customize imageunmute response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "imageunmute", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "imageunmute", "message", message)
        return await ctx.success("imageunmute response updated")

    @imageunmute_invoke_message.command(name="view", description="view imageunmute response")
    @has_permissions(manage_guild=True)
    async def imageunmute_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "imageunmute", "message")

    @group(
        name="reactionmute",
        aliases=["rmute", "reactmute"],
        description="reaction mute a member or role",
        example=",reactionmute @member",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def reactionmute(self, ctx, target: str, *, reason: str | None = None):
        """Reaction mute a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Not found\n> -# **no member or role matching** {target}")
        return await self._apply_special_mute(ctx, resolved, "r", reason=reason)

    @reactionmute.group(name="invoke", description="customize reactionmute messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @reactionmute_invoke.command(name="on", description="enable reactionmute response")
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionmute", "message", True)
        return await ctx.success("reactionmute response **enabled**")

    @reactionmute_invoke.command(name="off", description="disable reactionmute response")
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionmute", "message", False)
        return await ctx.success("reactionmute response **disabled**")

    @reactionmute_invoke.group(name="dm", description="customize reactionmute dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "reactionmute", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "reactionmute", "dm", message)
        return await ctx.success("reactionmute DM updated")

    @reactionmute_invoke_dm.command(name="on", description="enable reactionmute dm")
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionmute", "dm", True)
        return await ctx.success("reactionmute DM **enabled**")

    @reactionmute_invoke_dm.command(name="off", description="disable reactionmute dm")
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionmute", "dm", False)
        return await ctx.success("reactionmute DM **disabled**")

    @reactionmute_invoke_dm.command(name="view", description="view reactionmute dm")
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "reactionmute", "dm")

    @reactionmute_invoke.group(name="message", aliases=["msg"], description="customize reactionmute response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "reactionmute", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "reactionmute", "message", message)
        return await ctx.success("reactionmute response updated")

    @reactionmute_invoke_message.command(name="view", description="view reactionmute response")
    @has_permissions(manage_guild=True)
    async def reactionmute_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "reactionmute", "message")

    @group(
        name="reactionunmute",
        aliases=["runmute", "unreactionmute"],
        description="remove reaction mute from a member or role",
        example=",reactionunmute @member",
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True, manage_roles=True)
    async def reactionunmute(self, ctx, target: str, *, reason: str | None = None):
        """Remove reaction mute from a member or everyone with a role."""
        resolved = await self._resolve_member_or_role(ctx, target)
        if resolved is None:
            return await ctx.warn(f"Not found\n> -# **no member or role matching** {target}")
        return await self._apply_special_mute(
            ctx, resolved, "r", reason=reason, remove=True
        )

    @reactionunmute.group(name="invoke", description="customize reactionunmute messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @reactionunmute_invoke.command(name="on", description="enable reactionunmute response")
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionunmute", "message", True)
        return await ctx.success("reactionunmute response **enabled**")

    @reactionunmute_invoke.command(name="off", description="disable reactionunmute response")
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionunmute", "message", False)
        return await ctx.success("reactionunmute response **disabled**")

    @reactionunmute_invoke.group(name="dm", description="customize reactionunmute dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "reactionunmute", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "reactionunmute", "dm", message)
        return await ctx.success("reactionunmute DM updated")

    @reactionunmute_invoke_dm.command(name="on", description="enable reactionunmute dm")
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionunmute", "dm", True)
        return await ctx.success("reactionunmute DM **enabled**")

    @reactionunmute_invoke_dm.command(name="off", description="disable reactionunmute dm")
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "reactionunmute", "dm", False)
        return await ctx.success("reactionunmute DM **disabled**")

    @reactionunmute_invoke_dm.command(name="view", description="view reactionunmute dm")
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "reactionunmute", "dm")

    @reactionunmute_invoke.group(name="message", aliases=["msg"], description="customize reactionunmute response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "reactionunmute", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "reactionunmute", "message", message)
        return await ctx.success("reactionunmute response updated")

    @reactionunmute_invoke_message.command(name="view", description="view reactionunmute response")
    @has_permissions(manage_guild=True)
    async def reactionunmute_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "reactionunmute", "message")

    @group(
        name="hardban",
        description="keep a member banned",
        invoke_without_command=True,
    )
    @has_permissions(ban_members=True)
    async def hardban(self, ctx):
        """hardban a member"""
        if not await self._require_antinuke_for_hardban(ctx):
            return
        parsed = await parse_moderation_args(ctx, command_names=("hardban",), allow_duration=False)
        member = parsed.member
        user = parsed.user
        reason = parsed.reason
        target = member or user
        if target is None:
            return await ctx.warn("Could not find that user")
        if not await self._ensure_targetable(ctx, member, user):
            return
        if member and not await self._confirm_if_booster(ctx, member, "hardban"):
            return await ctx.warn("Action cancelled\n> -# **booster confirmation declined**")

        case_id = await self._create_case(
            ctx, action="hardban", target_id=target.id, reason=reason,
        )
        try:
            await ctx.guild.ban(
                discord.Object(id=target.id),
                delete_message_seconds=0,
                reason=self._audit_reason(ctx, reason),
            )
        except discord.Forbidden:
            return await ctx.fail("Missing permissions\n> -# **can't ban this member**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Ban failed\n> -# **{e}**")

        if getattr(self.db, "pool", None) is not None:
            await self.db.add_hardban(
                ctx.guild.id,
                target.id,
                ctx.author.id,
                self._default_reason(reason),
            )

        await self._send_modlog(
            ctx, action="hardban", target=target, case_id=case_id, reason=reason,
        )
        if await self._invoke_response(ctx, "hardban", user=target, reason=reason, case_id=case_id):
            return
        return await self._action_c2(ctx, f"Hardbanned **{target}**\n> -# **reason:** {self._default_reason(reason)}")

    @hardban.group(
        name="invoke",
        description="customize hardban punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def hardban_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @hardban_invoke.command(name="on", description="enable hardban response")
    @has_permissions(manage_guild=True)
    async def hardban_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "hardban", "message", True)
        return await ctx.success("hardban response **enabled**")

    @hardban_invoke.command(name="off", description="disable hardban response")
    @has_permissions(manage_guild=True)
    async def hardban_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "hardban", "message", False)
        return await ctx.success("hardban response **disabled**")

    @hardban_invoke.group(name="message", aliases=["msg"], description="customize hardban response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def hardban_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "hardban", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "hardban", "message", message)
        return await ctx.success("hardban response updated")

    @hardban_invoke_message.command(name="view", description="view hardban response")
    @has_permissions(manage_guild=True)
    async def hardban_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "hardban", "message")

    @command(
        name="hardban list",
        description="view list of hardbanned members",
    )
    @has_permissions(administrator=True)
    async def hardban_list(self, ctx):
        """list hardbanned members"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database unavailable\n> -# **could not load hardbans**")
        rows = await self.db.fetch_hardbans(ctx.guild.id)
        if not rows:
            return await ctx.warn("No hardbans\n> -# **no hardbanned members**")
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
        name="temprole",
        description="give a role temporarily to a user or users with a role",
        example=",temprole @member @Role 1h",
    )
    @has_permissions(manage_roles=True)
    async def temprole(
        self,
        ctx,
        target: discord.Member | discord.Role,
        role: discord.Role,
        duration_str: str,
        *,
        reason: str | None = None,
    ):
        """give a temporary role to a user or users with a role"""
        from core.tools.human.time import parse_duration, format_duration, discord_ts

        seconds = parse_duration(duration_str)
        if seconds is None or seconds <= 0:
            return await ctx.warn("Invalid duration\n> -# **use format:** `30s`, `5m`, `1h`, `2d`, `1w`")

        expires_at = discord.utils.utcnow() + __import__("datetime").timedelta(seconds=seconds)
        expires_ts = discord_ts(expires_at, "F")

        if isinstance(target, discord.Role):
            members_with_role = [m for m in target.members if not m.bot]
            if not members_with_role:
                return await ctx.warn(f"No members with {target.mention}")
            count = 0
            for member in members_with_role:
                if role not in member.roles:
                    with contextlib.suppress(discord.HTTPException):
                        await member.add_roles(role, reason=self._audit_reason(ctx, reason))
                        count += 1
                        self.bot.loop.create_task(self._temprole_remove_after(member, role, seconds))
            return await ctx.success(
                f"Gave {role.mention} to people with {target.mention}\n"
                f"> -# **until** {expires_ts}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            if role in target.roles:
                return await ctx.warn(f"{target.mention} already has {role.mention}")
            await target.add_roles(role, reason=self._audit_reason(ctx, reason))
            self.bot.loop.create_task(self._temprole_remove_after(target, role, seconds))
            return await ctx.success(
                f"Gave {role.mention} to {target.mention}\n"
                f"> -# **until** {expires_ts}",
            )

    async def _temprole_remove_after(self, member: discord.Member, role: discord.Role, seconds: int):
        """Remove a role after a duration."""
        import asyncio
        await asyncio.sleep(seconds)
        with contextlib.suppress(discord.HTTPException, discord.NotFound):
            if role in member.roles:
                await member.remove_roles(role, reason="temprole expired")

    @command(
        name="clearinvites",
        description="remove all existing invites in guild",
    )
    @has_permissions(manage_guild=True)
    async def clearinvites(self, ctx, params: str | None = None):
        """clear all invites"""
        from core.discord.views.confirm import ConfirmView

        invites = await ctx.guild.invites()
        if not invites:
            return await ctx.warn("No invites\n> -# **this server has no invites**")
        view = ConfirmView(ctx)
        message = (
            f"This will **delete all invites** in this server (**{len(invites)}**).\n"
            f"Are you sure you want to do this?"
        )
        if not await view.prompt(message):
            return await ctx.warn("Cancelled\n> -# **clearinvites was cancelled**")
        deleted = 0
        for invite in invites:
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await invite.delete(reason=f"clearinvites by {ctx.author}")
                deleted += 1
        return await ctx.success(f"Deleted **{deleted}** invite(s)")

    @command(
        name="drag",
        description="drag member(s) to the specified voice channel",
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
            return await ctx.warn("No members\n> -# **must mention at least one member**")
        moved = 0
        for member in members:
            if not member.voice or not member.voice.channel:
                continue
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await member.move_to(channel, reason=f"drag by {ctx.author}")
                moved += 1
        if not moved:
            return await ctx.warn("No moves\n> -# **no members could be moved**")
        return await ctx.success(f"Moved **{moved}** member(s) to {channel.mention}")

    @command(
        name="unbanall",
        description="unbans every member in a guild",
    )
    @has_permissions(ban_members=True)
    async def unbanall(self, ctx):
        """unban all members"""
        existing = self._unbanall_tasks.get(ctx.guild.id)
        if existing and not existing.done():
            return await ctx.warn("Already running\n> -# **unban all task is already in progress**")

        try:
            bans = [entry async for entry in ctx.guild.bans()]
        except discord.Forbidden:
            return await ctx.fail("Missing permissions\n> -# **need Ban Members permission to view the ban list**")

        if not bans:
            return await ctx.warn("No bans\n> -# **no members are banned**")

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
        description="cancels a unban all task running",
    )
    @has_permissions(ban_members=True)
    async def unbanall_cancel(self, ctx):
        """cancel unban all task"""
        task = self._unbanall_tasks.get(ctx.guild.id)
        if not task or task.done():
            return await ctx.warn("No task\n> -# **no unban all task is running**")
        task.cancel()
        self._unbanall_tasks.pop(ctx.guild.id, None)
        return await ctx.success("Task cancelled\n> -# **unban all**")

    @group(
        name="unban",
        usage="(user id or mention) <reason>",
        example="1269433308945711135 appealed",
        description="unbans the mentioned user",
        invoke_without_command=True,
    )
    @has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason=None):
        """unban a user"""
        was_hardbanned = False
        if getattr(self.db, "pool", None) is not None:
            with contextlib.suppress(Exception):
                was_hardbanned = await self.db.is_hardbanned(ctx.guild.id, user.id)
        if was_hardbanned and not await self._is_antinuke_admin(ctx):
            return await ctx.warn(
                "this user is **hardbanned**, you are missing the permission to **unhardban** them\n"
                "> -# **Permission Needed**: Antinuke Admin"
            )

        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound:
            return await ctx.warn(f"Not banned\n> -# **{user}** is not banned")
        except discord.Forbidden:
            return await ctx.warn("Missing permissions\n> -# **need Ban Members permission to view bans**")

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
            return await ctx.fail("Missing permissions\n> -# **need Ban Members permission to unban members**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Unban failed\n> -# **{user}**: {e}")

        if getattr(self.db, "pool", None) is not None:
            with contextlib.suppress(Exception):
                await self.db.remove_tempban(ctx.guild.id, user.id)
            if was_hardbanned:
                with contextlib.suppress(Exception):
                    await self.db.remove_hardban(ctx.guild.id, user.id)

        action_name = "unhardban" if was_hardbanned else "unban"
        await self._send_modlog(
            ctx,
            action=action_name,
            target=user,
            case_id=case_id,
            reason=reason,
        )
        if await self._invoke_response(ctx, "unban", user=user, reason=reason, case_id=case_id):
            return
        verb = "Unhardbanned" if was_hardbanned else "Unbanned"
        return await self._action_c2(ctx, self._action_line(verb, user, reason=reason))

    @unban.group(name="invoke", description="customize unban messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def unban_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @unban_invoke.command(name="on", description="enable unban response")
    @has_permissions(manage_guild=True)
    async def unban_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "unban", "message", True)
        return await ctx.success("unban response **enabled**")

    @unban_invoke.command(name="off", description="disable unban response")
    @has_permissions(manage_guild=True)
    async def unban_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "unban", "message", False)
        return await ctx.success("unban response **disabled**")

    @unban_invoke.group(name="dm", description="customize unban dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def unban_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "unban", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "unban", "dm", message)
        return await ctx.success("unban DM updated")

    @unban_invoke_dm.command(name="on", description="enable unban dm")
    @has_permissions(manage_guild=True)
    async def unban_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "unban", "dm", True)
        return await ctx.success("unban DM **enabled**")

    @unban_invoke_dm.command(name="off", description="disable unban dm")
    @has_permissions(manage_guild=True)
    async def unban_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "unban", "dm", False)
        return await ctx.success("unban DM **disabled**")

    @unban_invoke_dm.command(name="view", description="view unban dm")
    @has_permissions(manage_guild=True)
    async def unban_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "unban", "dm")

    @unban_invoke.group(name="message", aliases=["msg"], description="customize unban response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def unban_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "unban", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "unban", "message", message)
        return await ctx.success("unban response updated")

    @unban_invoke_message.command(name="view", description="view unban response")
    @has_permissions(manage_guild=True)
    async def unban_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "unban", "message")

    @group(
        name="softban",
        description="softbans the mentioned user and deleting 1 day of messages",
        invoke_without_command=True,
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
            return await ctx.warn("Action cancelled\n> -# **booster confirmation declined**")

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
        return await self._action_c2(ctx, f"Softbanned **{target_display}** - {self._default_reason(reason)}")

    @softban.group(
        name="invoke",
        description="customize softban punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def softban_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @softban_invoke.command(name="on", description="enable softban response")
    @has_permissions(manage_guild=True)
    async def softban_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "softban", "message", True)
        return await ctx.success("softban response **enabled**")

    @softban_invoke.command(name="off", description="disable softban response")
    @has_permissions(manage_guild=True)
    async def softban_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "softban", "message", False)
        return await ctx.success("softban response **disabled**")

    @softban_invoke.group(name="dm", description="customize softban dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def softban_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "softban", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "softban", "dm", message)
        return await ctx.success("softban DM updated")

    @softban_invoke_dm.command(name="on", description="enable softban dm")
    @has_permissions(manage_guild=True)
    async def softban_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "softban", "dm", True)
        return await ctx.success("softban DM **enabled**")

    @softban_invoke_dm.command(name="off", description="disable softban dm")
    @has_permissions(manage_guild=True)
    async def softban_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "softban", "dm", False)
        return await ctx.success("softban DM **disabled**")

    @softban_invoke_dm.command(name="view", description="view softban dm")
    @has_permissions(manage_guild=True)
    async def softban_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "softban", "dm")

    @softban_invoke.group(name="message", aliases=["msg"], description="customize softban response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def softban_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "softban", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "softban", "message", message)
        return await ctx.success("softban response updated")

    @softban_invoke_message.command(name="view", description="view softban response")
    @has_permissions(manage_guild=True)
    async def softban_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "softban", "message")

    @group(
        name="ban",
        usage="[duration] (member) [delete history] <reason>",
        example="2d @member Threatening members",
        description="bans the mentioned user",
        invoke_without_command=True,
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
        user = parsed.user
        reason = parsed.reason
        target = member or user
        if target is None:
            return await ctx.warn("Could not find that user")
        if not await self._ensure_targetable(ctx, member, user):
            return
        if member and not await self._confirm_if_booster(ctx, member, "ban"):
            return await ctx.warn("Action cancelled\n> -# **booster confirmation declined**")

        delete_days = parsed.delete_days or 0
        role_ids = [role.id for role in member.roles if role != ctx.guild.default_role] if member else []
        target_display = str(target)
        target_id = target.id

        case_id = await self._create_case(
            ctx,
            action="ban",
            target_id=target_id,
            reason=reason,
        )
        await self._invoke_dm(ctx, target, "ban", reason=reason, case_id=case_id)

        try:
            await ctx.guild.ban(
                discord.Object(id=target_id),
                delete_message_seconds=delete_days * 86400,
                reason=self._audit_reason(ctx, reason),
            )
        except discord.Forbidden:
            return await ctx.fail("Missing permissions\n> -# **can't ban this member**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Ban failed\n> -# **{e}**")

        await self._send_modlog(
            ctx,
            action="ban",
            target=target,
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
        if await self._invoke_response(ctx, "ban", user=target, reason=reason, case_id=case_id):
            return
        purge = f" (purged **{delete_days}d**)" if delete_days else ""
        return await self._action_c2(ctx, f"Banned **{target_display}**{purge} - {self._default_reason(reason)}")

    @ban.group(
        name="invoke",
        description="customize ban punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def ban_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @ban_invoke.command(name="on", description="enable ban response")
    @has_permissions(manage_guild=True)
    async def ban_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "ban", "message", True)
        return await ctx.success("ban response **enabled**")

    @ban_invoke.command(name="off", description="disable ban response")
    @has_permissions(manage_guild=True)
    async def ban_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "ban", "message", False)
        return await ctx.success("ban response **disabled**")

    @ban_invoke.group(name="dm", description="customize ban dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def ban_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "ban", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "ban", "dm", message)
        return await ctx.success("ban DM updated")

    @ban_invoke_dm.command(name="on", description="enable ban dm")
    @has_permissions(manage_guild=True)
    async def ban_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "ban", "dm", True)
        return await ctx.success("ban DM **enabled**")

    @ban_invoke_dm.command(name="off", description="disable ban dm")
    @has_permissions(manage_guild=True)
    async def ban_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "ban", "dm", False)
        return await ctx.success("ban DM **disabled**")

    @ban_invoke_dm.command(name="view", description="view ban dm")
    @has_permissions(manage_guild=True)
    async def ban_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "ban", "dm")

    @ban_invoke.group(name="message", aliases=["msg"], description="customize ban response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def ban_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "ban", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "ban", "message", message)
        return await ctx.success("ban response updated")

    @ban_invoke_message.command(name="view", description="view ban response")
    @has_permissions(manage_guild=True)
    async def ban_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "ban", "message")

    @group(
        name="kick",
        usage="(member) <reason>",
        example="@member spamming",
        description="kick the mentioned user",
        invoke_without_command=True,
    )
    @has_permissions(kick_members=True)
    async def kick(self, ctx):
        """kick a member"""
        parsed = await parse_moderation_args(ctx, command_names=("kick",), allow_duration=False)
        member = parsed.member
        user = parsed.user
        reason = parsed.reason
        target = member or user
        if target is None:
            return await ctx.warn("Could not find that user")
        if not await self._ensure_targetable(ctx, member, user):
            return
        if member and not await self._confirm_if_booster(ctx, member, "kick"):
            return await ctx.warn("Action cancelled\n> -# **booster confirmation declined**")

        if member is None:
            return await ctx.warn("User is not in this server\n> -# **can't kick a user who isn't a member**")

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
        return await self._action_c2(ctx, f"Kicked **{target_display}** - {self._default_reason(reason)}")

    @kick.group(
        name="invoke",
        description="customize kick punishment messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def kick_invoke(self, ctx):
        return await ctx.send_help(ctx.command)

    @kick_invoke.command(name="on", description="enable kick response")
    @has_permissions(manage_guild=True)
    async def kick_invoke_on(self, ctx):
        await self._set_invoke_enabled(ctx, "kick", "message", True)
        return await ctx.success("kick response **enabled**")

    @kick_invoke.command(name="off", description="disable kick response")
    @has_permissions(manage_guild=True)
    async def kick_invoke_off(self, ctx):
        await self._set_invoke_enabled(ctx, "kick", "message", False)
        return await ctx.success("kick response **disabled**")

    @kick_invoke.group(name="dm", description="customize kick dm", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def kick_invoke_dm(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "kick", "dm", result.script)
        except Exception:
            await self._set_invoke(ctx, "kick", "dm", message)
        return await ctx.success("kick DM updated")

    @kick_invoke_dm.command(name="on", description="enable kick dm")
    @has_permissions(manage_guild=True)
    async def kick_invoke_dm_on(self, ctx):
        await self._set_invoke_enabled(ctx, "kick", "dm", True)
        return await ctx.success("kick DM **enabled**")

    @kick_invoke_dm.command(name="off", description="disable kick dm")
    @has_permissions(manage_guild=True)
    async def kick_invoke_dm_off(self, ctx):
        await self._set_invoke_enabled(ctx, "kick", "dm", False)
        return await ctx.success("kick DM **disabled**")

    @kick_invoke_dm.command(name="view", description="view kick dm")
    @has_permissions(manage_guild=True)
    async def kick_invoke_dm_view(self, ctx):
        return await self._view_invoke(ctx, "kick", "dm")

    @kick_invoke.group(name="message", aliases=["msg"], description="customize kick response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def kick_invoke_message(self, ctx, *, message=None):
        if message is None:
            return await ctx.send_help(ctx.command)
        from core.managers.converters import EmbedConverter
        try:
            result = await EmbedConverter().convert(ctx, message)
            await self._set_invoke(ctx, "kick", "message", result.script)
        except Exception:
            await self._set_invoke(ctx, "kick", "message", message)
        return await ctx.success("kick response updated")

    @kick_invoke_message.command(name="view", description="view kick response")
    @has_permissions(manage_guild=True)
    async def kick_invoke_message_view(self, ctx):
        return await self._view_invoke(ctx, "kick", "message")

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
        description="bans the most recently joined members",
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
            return await ctx.warn("No members found\n> -# **no recent members matched the criteria**")
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
        return await self._action_c2(ctx, f"Banned **{banned}** recently joined member(s)")

    @command(
        name="ban purge",
        usage="(delete history)",
        example="7",
        description="bans all members and purges their recent messages",
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
            return await ctx.warn("No members found\n> -# **no members available to ban**")
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
        return await self._action_c2(ctx, f"Banned **{banned}** member(s) with **{delete_days}d** message purge")

    @command(
        name="temprole",
        description="no description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole(self, ctx, member: discord.Member, duration: str, role: discord.Role):
        """give temporary role"""
        if not await self._ensure_targetable(ctx, member):
            return
        if role >= ctx.guild.me.top_role:
            return await ctx.warn("Invalid role\n> -# **role is higher than my top role**")
        seconds = self._parse_duration_seconds(duration)
        if not seconds or seconds < 60:
                return await ctx.warn("Invalid duration\n> -# **must be at least `60 seconds` (e.g. `30m`, `2h`, `7d`)**")
        expires_at = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await member.add_roles(role, reason=f"temprole by {ctx.author}")
        except discord.HTTPException as e:
            return await ctx.fail(f"Role update failed\n> -# **{e}**")
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
        description="no description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole_list(self, ctx):
        """list temporary roles"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database unavailable\n> -# **could not load temporary roles**")
        rows = await self.db.fetch_temproles(ctx.guild.id)
        if not rows:
            return await ctx.warn("No active roles\n> -# **no temporary roles are currently active**")
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
        name="newmembers",
        description="view list of recently joined members",
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
            return await ctx.warn("No members found\n> -# **no members matched the criteria**")
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
        description="chunk ban recently joined members",
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
        return await self._action_c2(ctx, f"Banned **{banned}** recent member(s)")

    @command(
        name="talk",
        description="toggle a channel to text for a role",
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
            return await ctx.warn("Text channels only\n> -# **this command only works on text channels**")
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

    async def _parse_channel_and_target(
        self, ctx, first: str | None, second: str | None
    ):
        """Parse optional channel + user/role target in any order.

        Returns (channel, target_or_none).
        Handles: ,hide @user | ,hide #chan @user | ,hide #chan | ,hide
        """
        if first is None:
            return ctx.channel, None

        try:
            ch = await commands.TextChannelConverter().convert(ctx, first)
            return ch, second
        except CommandError:
            return ctx.channel, first

    async def _resolve_hide_target(
        self, ctx, token: str | None
    ) -> discord.Role | discord.Member:
        """Resolve optional user/role; default to @everyone (members)."""
        if not token:
            return ctx.guild.default_role

        converters = (
            commands.RoleConverter(),
            commands.MemberConverter(),
        )
        for converter in converters:
            try:
                return await converter.convert(ctx, token)
            except CommandError:
                continue
        raise CommandError(f"couldn't find a role or member matching `{token}`")

    async def _hide_channel(
        self,
        ctx,
        channel: discord.abc.GuildChannel,
        target: discord.Role | discord.Member,
    ) -> str | None:
        """Hide channel from target. Returns warning text if already hidden, else None."""
        if not isinstance(channel, discord.abc.GuildChannel):
            raise CommandError("this command only works on guild channels")

        current = channel.overwrites_for(target).view_channel
        if current is False:
            who = (
                "everyone"
                if isinstance(target, discord.Role) and target.is_default()
                else target.mention
            )
            return f"Channel is **already** hidden from {who}"

        overwrites = channel.overwrites_for(target)
        overwrites.view_channel = False
        await channel.set_permissions(
            target,
            overwrite=overwrites,
            reason=f"Channel hidden by {ctx.author}",
        )
        return None

    async def _unhide_channel(
        self,
        ctx,
        channel: discord.abc.GuildChannel,
        target: discord.Role | discord.Member,
    ) -> str | None:
        """Unhide channel for target. Returns warning text if not hidden, else None."""
        if not isinstance(channel, discord.abc.GuildChannel):
            raise CommandError("this command only works on guild channels")

        current = channel.overwrites_for(target).view_channel
        
        if current is None:
            who = (
                "everyone"
                if isinstance(target, discord.Role) and target.is_default()
                else target.mention
            )
            return f"Channel is **not** hidden from {who}"

        overwrites = channel.overwrites_for(target)
        overwrites.view_channel = None
        await channel.set_permissions(
            target,
            overwrite=overwrites,
            reason=f"Channel unhidden by {ctx.author}",
        )
        return None

    def _hide_target_label(self, target: discord.Role | discord.Member) -> str:
        if isinstance(target, discord.Role) and target.is_default():
            return "**members**"
        return target.mention

    @command(
        name="hide",
        brief="manage channels",
        description="hide a channel from everyone or a specific user/role",
        usage="hide [channel] [user or role]",
        example=",hide #general @role",
    )
    @has_permissions(manage_channels=True)
    async def hide(
        self,
        ctx,
        first: str = None,
        second: str = None,
    ):
        """Hide a channel from everyone"""
        channel, target_str = await self._parse_channel_and_target(ctx, first, second)
        resolved = await self._resolve_hide_target(ctx, target_str)
        try:
            already = await self._hide_channel(ctx, channel, resolved)
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to hide channel: {e}")
        if already:
            return await ctx.warn(already)
        return await ctx.success(
            f"Hid {channel.mention} from {self._hide_target_label(resolved)}"
        )

    @command(
        name="unhide",
        brief="manage roles",
        description="unhide a channel from everyone or a specific user/role",
        usage="unhide [channel] [user or role]",
        example=",unhide #commands",
    )
    @has_permissions(manage_channels=True)
    async def unhide(
        self,
        ctx,
        first: str = None,
        second: str = None,
    ):
        """Unhide a channel from everyone"""
        channel, target_str = await self._parse_channel_and_target(ctx, first, second)
        resolved = await self._resolve_hide_target(ctx, target_str)
        try:
            not_hidden = await self._unhide_channel(ctx, channel, resolved)
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to unhide channel: {e}")
        if not_hidden:
            return await ctx.warn(not_hidden)
        return await ctx.success(
            f"Unhid {channel.mention} from {self._hide_target_label(resolved)}"
        )

    @command(
        name="hideall",
        aliases=["hide-all"],
        brief="manage channels",
        description="hide all channels from everyone or a specific user/role",
        usage="hideall [user or role]",
        example=",hideall @role",
    )
    @has_permissions(manage_channels=True)
    async def hideall(self, ctx, *, target: str = None):
        """Hide all channels from members (or a user/role)"""
        from core.discord.views.confirm import ThreeButtonConfirmView, ConfirmChoice

        resolved = await self._resolve_hide_target(ctx, target)
        already_hidden = []
        to_hide = []

        for channel in list(ctx.guild.channels):
            if not isinstance(channel, discord.abc.GuildChannel):
                continue
            current = channel.overwrites_for(resolved).view_channel
            if current is False:
                already_hidden.append(channel)
            else:
                to_hide.append(channel)

        if not to_hide:
            return await ctx.warn(
                f"All channels are **already** hidden from {self._hide_target_label(resolved)}"
            )

        if already_hidden:
            msg = (
                f"**{len(already_hidden)}** channel(s) were **already hidden** from "
                f"{self._hide_target_label(resolved)} before using **hideall**\n"
                f"> -# **approve hides all channels** ;\n"
                f"> -# **deny hides only the channels that weren't hidden** ;\n"
                f"> -# **cancel this using the cancel button**"
            )
        else:
            msg = (
                f"**{len(to_hide)}** channel(s) will be hidden from "
                f"{self._hide_target_label(resolved)}.\n"
                f"> -# **approve hides all channels** ;\n"
                f"> -# **deny hides only the channels that weren't hidden** ;\n"
                f"> -# **cancel this using the cancel button**"
            )

        view = ThreeButtonConfirmView(ctx, show_cancel=True)
        choice = await view.prompt(msg)

        if choice == ConfirmChoice.CANCEL:
            return await ctx.warn("Cancelled\n> -# **hideall was cancelled**")

        if choice == ConfirmChoice.DENY:
            applied = 0
            for channel in to_hide:
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    await self._hide_channel(ctx, channel, resolved)
                    applied += 1
            return await ctx.success(
                f"Hid **{applied}** channel(s) from {self._hide_target_label(resolved)}"
            )

        applied = 0
        for channel in list(ctx.guild.channels):
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await self._hide_channel(ctx, channel, resolved)
                applied += 1

        return await ctx.success(
            f"Hid **{applied}** channel(s) from {self._hide_target_label(resolved)}"
        )

    @command(
        name="unhideall",
        aliases=["unhide-all"],
        brief="manage roles",
        description="unhide all channels from everyone or a specific user/role",
        usage="unhideall [user or role]",
        example=",unhideall @role",
    )
    @has_permissions(manage_channels=True)
    async def unhideall(self, ctx, *, target: str = None):
        """Unhide all channels for members (or a user/role)"""
        from core.discord.views.confirm import ThreeButtonConfirmView, ConfirmChoice

        resolved = await self._resolve_hide_target(ctx, target)
        hidden_channels = []
        already_unhidden = []

        for channel in list(ctx.guild.channels):
            if not isinstance(channel, discord.abc.GuildChannel):
                continue
            current = channel.overwrites_for(resolved).view_channel
            if current is False:
                hidden_channels.append(channel)
            else:
                already_unhidden.append(channel)

        if not hidden_channels:
            return await ctx.warn(
                f"No channels are hidden from {self._hide_target_label(resolved)}"
            )

        if already_unhidden:
            msg = (
                f"**{len(hidden_channels)}** channel(s) are **currently hidden** from "
                f"{self._hide_target_label(resolved)}\n"
                f"> -# **approve unhides all channels** ;\n"
                f"> -# **deny unhides only the channels that were hidden** ;\n"
                f"> -# **cancel this using the cancel button**"
            )
        else:
            msg = (
                f"**{len(hidden_channels)}** channel(s) will be unhidden from "
                f"{self._hide_target_label(resolved)}.\n"
                f"> -# **approve unhides all channels** ;\n"
                f"> -# **deny unhides only the channels that were hidden** ;\n"
                f"> -# **cancel this using the cancel button**"
            )

        view = ThreeButtonConfirmView(ctx, show_cancel=True)
        choice = await view.prompt(msg)

        if choice == ConfirmChoice.CANCEL:
            return await ctx.warn("Cancelled\n> -# **unhideall was cancelled**")

        if choice == ConfirmChoice.DENY:
            applied = 0
            for channel in hidden_channels:
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    await self._unhide_channel(ctx, channel, resolved)
                    applied += 1
            return await ctx.success(
                f"Unhid **{applied}** channel(s) from {self._hide_target_label(resolved)}"
            )

        applied = 0
        for channel in list(ctx.guild.channels):
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await self._unhide_channel(ctx, channel, resolved)
                applied += 1

        return await ctx.success(
            f"Unhid **{applied}** channel(s) from {self._hide_target_label(resolved)}"
        )

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
        aliases=["setme","setmod"],
        description="start process for setting up the moderation system",
    )
    async def setup(self, ctx):
        """interactive automatic setup for vain - guild owner only"""
        from .extended.setup import (
            SetupView,
            format_cooldown_left,
            setup_on_cooldown,
        )

        if ctx.guild is None:
            return
        owners = getattr(self.bot, "owners", None) or []
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id not in owners:
            return await ctx.warn(
                "You are **missing** the permission to **setup** vain\n"
                "> -# **Permission Needed: Guild Owner**"
            )

        left = setup_on_cooldown(ctx.guild.id)
        if left is not None:
            wait = format_cooldown_left(left)
            return await ctx.warn(
                f"Setup is on cooldown\n> -# **try again in** `{wait}`"
            )

        prefix = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", None) or ","
        view = SetupView(
            self.bot,
            guild=ctx.guild,
            author_id=ctx.author.id,
            prefix=str(prefix),
        )
        msg = await ctx.send(view=view)
        view.message = msg

    @command(
        name="unsetup",
        aliases=["unset", "unsetme", "unsetmod", "reset"],
        description="remove moderation system setup (categories and channels)",
    )
    @has_permissions(administrator=True)
    async def unsetup(self, ctx):
        """remove moderation setup"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove the **moderation system** setup?\n\n"
            "> -# This **removes** the configured channels and roles created\n"
            "> -# however this does **not** affect **voicemaster**, **antinuke** and **antiraid**.\n"
            "> -# **this action can't be undone**, proceed with caution"
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **moderation unsetup was cancelled**")

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

            await Settings.delete_modlog_config(self.bot.db, ctx.guild.id)

        if removed:
            await ctx.success(
                f"Removed all channels and roles\n"
                f"Use `{ctx.invoke_prefix}setup` to recreate them."
            )
        else:
            await ctx.warn("No setup found\n> -# **no moderation setup channels to remove**")

    @command(
        name="setupjail",
        description="sets up the jail role, channel, and permissions",
    )
    @has_permissions(manage_guild=True, manage_channels=True)
    async def setupjail(self, ctx):
        """setup jail system"""
        async with ctx.typing():
            row = await self._ensure_jail_ready(ctx)
            if not row:
                return await ctx.warn("Jail setup failed\n> -# **could not create jail channel or role**")
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
        description="remove the jail system setup (channel, role and permissions)",
    )
    @has_permissions(manage_guild=True, manage_channels=True, manage_roles=True)
    async def unsetupjail(self, ctx):
        """remove jail system setup"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove the **jail system**? "
            "This **deletes** the jail channel/category and the `Jailed` role. "
            "**This can't be undone.**"
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **jail unsetup was cancelled**")

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
                f"Use `{ctx.invoke_prefix}setupjail` to recreate them."
            )
        else:
            await ctx.warn("No jail setup found\n> -# **no jail system to remove**")

    @command(
        name="setupmute",
        description="sets up muted roles and channel permissions",
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

            await Settings.set_server_mute_roles(
                self.bot.db,
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
        description="remove the mute system setup (muted roles and permissions)",
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def unsetupmute(self, ctx):
        """remove mute system setup"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove the **mute system**? "
            "This **deletes** the `Muted`, `Image Muted` and `Reaction Muted` roles "
            "and clears the mute configuration. **This can't be undone.**"
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **mute unsetup was cancelled**")

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
                f"Use `{ctx.invoke_prefix}setupmute` to recreate them."
            )
        else:
            await ctx.warn("No mute setup found\n> -# **no mute system to remove**")

    @command(
        name="rename",
        description="assigns the mentioned user a new nickname in the guild",
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
            return await ctx.fail("Missing permissions\n> -# **need Manage Nicknames permission**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Rename failed\n> -# **{e}**")
        return await ctx.success(f"Renamed **{member}** to **{newnick[:32]}**")

    @command(
        name="raid",
        description="remove all members that joined in the time provided in the event of a raid",
    )
    @has_permissions(ban_members=True, kick_members=True)
    async def raid(self, ctx, time: str, action: str, *, reason: str | None = None):
        """raid mode"""
        seconds = self._parse_duration_seconds(time)
        if not seconds:
            return await ctx.warn("Please provide a **valid duration**\n> -# **examples: `30m`, `2h`, `1d`**")
        action = action.lower().strip()
        if action not in {"ban", "kick"}:
            return await ctx.warn("Invalid action\n> -# **must be** `ban` or `kick`")

        cutoff = discord.utils.utcnow() - timedelta(seconds=seconds)
        targets = [
            m for m in ctx.guild.members
            if not m.bot
            and m.joined_at
            and m.joined_at >= cutoff
            and m.id not in {ctx.author.id, ctx.guild.owner_id, ctx.guild.me.id}
        ]
        if not targets:
            return await ctx.warn("No members found\n> -# **no members joined in that time window**")

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
        description="change the current channel topic",
    )
    @has_permissions(manage_channels=True)
    async def topic(self, ctx, *, text: str):
        """change channel topic"""
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.warn("Text channels only\n> -# **this command only works in text channels**")
        await ctx.channel.edit(topic=text[:1024], reason=f"topic by {ctx.author}")
        return await ctx.success("Updated this channel's **topic**")

    @command(
        name="naughty",
        aliases=["nsfw"],
        usage="[duration] [channel]",
        example="30s  or  1d #channel",
        description="toggle nsfw on a channel (indefinitely or for a duration)",
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
                    return await ctx.warn("Invalid duration\n> -# **use e.g. 30s, 5m, 1h, 1d, 1w**")
        else:
            seconds = self._parse_duration_seconds(duration) if duration else None
            if duration and seconds is None:
                return await ctx.warn(
                    f"Invalid duration\n> -# **{duration}** is not valid (examples: 30s, 5m, 1h, 1d, 1w)"
                )

        channel = channel or ctx.channel
        if not isinstance(channel, discord.TextChannel):
            return await ctx.warn("Text channels only\n> -# **this command only works on text channels**")

        if not channel.permissions_for(ctx.guild.me).manage_channels:
            return await ctx.warn("Missing permissions\n> -# **need Manage Channels for that channel**")

        
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
            return await ctx.fail("Missing permissions\n> -# **can't edit this channel**")
        except discord.HTTPException as e:
            return await ctx.fail(f"Channel update failed\n> -# **{e}**")

        if seconds and seconds > 0:
            label = self._format_duration(seconds)
            await ctx.success(
                f"NSFW {action} on {channel.mention} for **{label}**\n"
                f"> -# **reverts to:** {'NSFW' if was_nsfw else 'SFW'}"
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
            await ctx.success(f"NSFW {action} on {channel.mention}\n> -# **duration:** indefinitely")

    @command(
        name="permissions",
        description="check permissions for member or myself",
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
