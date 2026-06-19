from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import discord
from discord import Embed
from discord.ext import commands, tasks
from discord.ext.commands import CommandError, FlagConverter, flag, group

from core.discord.package import Package
from core.tools.convert import MemberConvert, StatusConvert
from core.tools.flags import AntiNukeFlags
from core.tools.permissions import DANGEROUS_PERMISSIONS, normalize_dangerous_permission

from .models import AntinukeConfig, PermissionWatch

SHORT_WINDOW = 60
LONG_WINDOW = 20 * 60
LONG_THRESHOLD_FACTOR = 2
AUDIT_LOOKBACK = 15

MODULE_NAMES = {
    "botadd": "bot add",
    "webhook": "webhook",
    "emoji": "emoji",
    "ban": "ban",
    "kick": "kick",
    "channel": "channel",
    "role": "role",
    "vanity": "vanity",
}

SEVERITY_RANK = {
    "warn": 1,
    "stripstaff": 2,
    "jail": 3,
    "kick": 4,
    "ban": 5,
}

RECENT_CMD_WINDOW = 20


class EnableFlags(FlagConverter, prefix="--", delimiter=" ", case_insensitive=True):
    recommended: Optional[bool] = flag(default=None)


class Antinuke(Package):
    """server antinuke configuration and enforcement."""

    def __init__(self, bot):
        super().__init__(bot)
        self.config: dict[int, AntinukeConfig] = {}
        self._stale_cmd_actions: dict[tuple[int, int, str, int], datetime] = {}

    async def cog_load(self) -> None:
        if self.bot.db.pool is not None:
            self.config_sync.start()

    async def cog_unload(self) -> None:
        if self.config_sync.is_running():
            self.config_sync.cancel()

    async def cog_check(self, ctx) -> bool:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")

        if ctx.command and ctx.command.name == "admin":
            if ctx.author.id != ctx.guild.owner_id:
                raise CommandError(
                    "You must be the **server owner** to run this command."
                )
            return True

        admins = set(
            await self.db.fetchval(
                "SELECT admins FROM antinuke WHERE guild_id = $1", ctx.guild.id
            )
            or []
        )
        admins.add(ctx.guild.owner_id)
        if ctx.author.id not in admins:
            raise CommandError("You must be an **antinuke admin** to run this command.")
        return True

    @tasks.loop(seconds=30)
    async def config_sync(self) -> None:
        rows = await self.db.fetch("SELECT * FROM antinuke", cached=False)
        self.config = {
            row.guild_id: AntinukeConfig.from_record(row)
            for row in rows
        }

    async def _load_config(self, guild_id: int) -> AntinukeConfig:
        row = await self.db.fetchrow(
            "SELECT * FROM antinuke WHERE guild_id = $1",
            guild_id,
            cached=False,
        )
        cfg = AntinukeConfig.from_record(row)
        if row:
            self.config[guild_id] = cfg
        else:
            self.config.pop(guild_id, None)
        return cfg

    async def _guild_config(self, guild_id: int) -> AntinukeConfig:
        if cfg := self.config.get(guild_id):
            return cfg
        return await self._load_config(guild_id)

    def _toggle_icon(self, active: bool) -> str:
        emojis = self.bot.config.get("emojis", {})
        return emojis.get("success", "✅") if active else emojis.get("fail", "❌")

    def _concatenate(self, parts: list[str]) -> str:
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return f"{', '.join(parts[:-1])} and {parts[-1]}"

    def _build_module_payload(
        self,
        *,
        status: bool,
        with_threshold: bool,
        with_command: bool,
        flags: dict[str, Any],
    ) -> dict[str, Any]:
        penalty = str(flags.get("punishment") or "kick").lower()
        if penalty not in {"ban", "kick", "stripstaff", "warn", "jail"}:
            raise CommandError(
                "punishment must be `ban`, `kick`, `jail`, `warn`, or `stripstaff`"
            )

        payload: dict[str, Any] = {
            "status": status,
            "punishment": penalty,
        }
        if with_threshold:
            limit = int(flags.get("threshold") or 3)
            if limit < 1 or limit > 6:
                raise CommandError("threshold must be between **1** and **6**")
            payload["threshold"] = limit
        if with_command:
            payload["command"] = bool(flags.get("command"))
        return payload

    async def _commit_module(self, guild_id: int, name: str, payload: dict[str, Any]) -> None:
        await self.db.execute(
            f"""
            INSERT INTO antinuke (guild_id, {name})
            VALUES ($1, $2::JSONB)
            ON CONFLICT (guild_id) DO UPDATE SET
                {name} = EXCLUDED.{name};
            """,
            guild_id,
            payload,
        )
        await self._load_config(guild_id)

    async def _adjust_module(
        self,
        ctx,
        name: str,
        status: bool,
        *,
        with_threshold: bool = False,
        with_command: bool = False,
    ):
        payload = self._build_module_payload(
            status=status,
            with_threshold=with_threshold,
            with_command=with_command,
            flags=ctx.flags,
        )
        await self._commit_module(ctx.guild.id, name, payload)

        label = MODULE_NAMES[name]
        if not status:
            return await ctx.success(f"Turned **{label}** antinuke protection off")

        summary = [f"action: **{payload['punishment']}**"]
        if with_threshold:
            summary.append(f"limit: **{payload['threshold']}**")
        if with_command:
            summary.append(
                f"cmd: **{'yes' if payload['command'] else 'no'}**"
            )
        return await ctx.success(
            f"**{label}** antinuke is now active ({self._concatenate(summary)})"
        )

    def _count_perms(self, config: AntinukeConfig, *, kind: str) -> int:
        return config.permission_count(kind)

    def _build_reason(self, module: str, limit: int | None = None) -> str:
        if limit:
            return (
                f"antinuke: {module} exceeded {limit} in {SHORT_WINDOW}s"
            )
        return f"antinuke: {module} violation"

    def _verb_for(self, action: str | None) -> str:
        mapping = {
            "ban": "banned",
            "kick": "kicked",
            "warn": "warned",
            "jail": "jailed",
            "stripstaff": "stripped of staff",
            "tempban": "tempbanned",
            "softban": "softbanned",
        }
        return mapping.get((action or "action").lower(), action or "action")

    def _owner_verb(self, penalty: str | None) -> str:
        if (penalty or "").lower() == "stripstaff":
            return "stripped of staff"
        return self._verb_for(penalty)

    def _penalty_verb(self, penalty: str | None) -> str:
        mapping = {
            "ban": "banned",
            "kick": "kicked",
            "jail": "jailed",
            "stripstaff": "stripped of staff",
            "warn": "warned",
        }
        return mapping.get((penalty or "kick").lower(), "punished")

    def _strongest_penalty(self, candidates: Iterable[PermissionWatch]) -> str:
        ordered = sorted(
            candidates,
            key=lambda item: SEVERITY_RANK.get(item.punishment, 0),
            reverse=True,
        )
        if not ordered:
            return "kick"
        return ordered[0].punishment

    def _purge_stale_actions(self) -> None:
        now = discord.utils.utcnow()
        dead = [
            key
            for key, expiry in self._stale_cmd_actions.items()
            if expiry <= now
        ]
        for key in dead:
            self._stale_cmd_actions.pop(key, None)

    def _note_cmd_action(
        self,
        guild_id: int,
        actor_id: int,
        module_name: str,
        subject_id: int,
    ) -> None:
        self._purge_stale_actions()
        self._stale_cmd_actions[(guild_id, actor_id, module_name, subject_id)] = (
            discord.utils.utcnow() + timedelta(seconds=RECENT_CMD_WINDOW)
        )

    def _is_recent_cmd_action(
        self,
        guild_id: int,
        actor_id: int,
        module_name: str,
        subject_id: int,
    ) -> bool:
        self._purge_stale_actions()
        return (guild_id, actor_id, module_name, subject_id) in self._stale_cmd_actions

    def _bypass_set(self, guild: discord.Guild, config: AntinukeConfig) -> set[int]:
        ids = set(config.whitelist)
        ids.update(config.admins)
        ids.add(guild.owner_id)
        if self.bot.user:
            ids.add(self.bot.user.id)
        me = guild.me or guild.get_member(self.bot.user.id if self.bot.user else 0)
        if me:
            ids.add(me.id)
        return ids

    async def _find_member(self, guild: discord.Guild, uid: int) -> discord.Member | None:
        if member := guild.get_member(uid):
            return member
        with contextlib.suppress(discord.HTTPException):
            return await guild.fetch_member(uid)
        return None

    async def _entry_user(
        self,
        guild: discord.Guild,
        entry: discord.AuditLogEntry | None,
    ) -> discord.Member | None:
        if not entry or not entry.user:
            return None
        if isinstance(entry.user, discord.Member):
            return entry.user
        return await self._find_member(guild, entry.user.id)

    async def _fetch_latest_log(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        *,
        target_id: int | None = None,
        limit: int = 6,
    ) -> discord.AuditLogEntry | None:
        with contextlib.suppress(
            discord.Forbidden,
            discord.NotFound,
            discord.HTTPException,
        ):
            async for entry in guild.audit_logs(limit=limit, action=action):
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age > AUDIT_LOOKBACK:
                    continue
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                return entry
        return None

    async def _alert_guild_owner(self, guild: discord.Guild, body: str) -> None:
        owner = guild.owner
        if owner is None:
            with contextlib.suppress(discord.HTTPException):
                owner = await guild.fetch_member(guild.owner_id)
        if owner is None and self.bot.user:
            with contextlib.suppress(discord.HTTPException):
                owner = await self.bot.fetch_user(guild.owner_id)
        if owner is None:
            return
        embed = Embed(color=self.color, description=body)
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await owner.send(embed=embed)

    def _server_link_view(self, guild: discord.Guild) -> discord.ui.View:
        view = discord.ui.View()
        label = f"From {guild.name}"
        if len(label) > 80:
            label = f"From {guild.name[:70]}..."
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=label,
                url=f"https://discord.com/channels/{guild.id}",
            )
        )
        return view

    async def _dispatch_dm(
        self,
        user: discord.abc.User,
        *,
        action: str,
        guild: discord.Guild,
        moderator: discord.abc.User,
        reason: str,
        case_id: int | None = None,
    ) -> None:
        embed = Embed(color=self.color)
        title = f"You were {self._verb_for(action.replace(' (auto)', ''))}"
        if case_id is not None:
            title += f" [#{case_id}]"
        embed.add_field(
            name=title,
            value=(
                f"> **Staff:** @{getattr(moderator, 'name', str(moderator))}\n"
                f"> **Cause:** {reason or 'no reason provided'}"
            ),
            inline=False,
        )
        embed.set_footer(text="Contact staff if you believe this was an error.")
        embed.timestamp = discord.utils.utcnow()
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await user.send(embed=embed, view=self._server_link_view(guild))

    async def _record_case(
        self,
        guild: discord.Guild,
        *,
        action: str,
        target_id: int,
        moderator: discord.abc.User,
        reason: str,
    ) -> int | None:
        if getattr(self.db, "pool", None) is None:
            return None

        case_id = await self.db.create_case(
            guild_id=guild.id,
            action=action,
            target_id=target_id,
            moderator_id=moderator.id,
            reason=reason,
        )
        channel_id = await self.db.get_modlog_channel(guild.id)
        if not channel_id:
            return case_id
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return case_id

        embed = Embed(
            color=self.color,
            title=f"Case #{case_id}",
            description=(
                f"**Action:** {action}\n"
                f"**User:** <@{target_id}> (`{target_id}`)\n"
                f"**Staff:** {getattr(moderator, 'mention', str(moderator))} (`{moderator.id}`)\n"
                f"> **Cause:** {reason or 'no reason provided'}"
            ),
            timestamp=discord.utils.utcnow(),
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return case_id

    async def _confine_member(
        self,
        member: discord.Member,
        *,
        reason: str,
    ) -> bool:
        settings = await self.db.get_server_settings(member.guild.id)
        jail_role_id = getattr(settings, "jail_role_id", None) if settings else None
        if not jail_role_id:
            return False

        jail_role = member.guild.get_role(int(jail_role_id))
        if jail_role is None:
            return False

        remove_roles = not (settings and settings.jail_remove_roles is False)
        if remove_roles:
            roles_to_remove = [
                role
                for role in member.roles
                if role not in {member.guild.default_role, jail_role}
            ]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=reason)

        if jail_role not in member.roles:
            await member.add_roles(jail_role, reason=reason)
        return True

    async def _demote_staff(
        self,
        member: discord.Member,
        *,
        reason: str,
    ) -> bool:
        role_ids = set(await self.db.list_staff_roles(member.guild.id))
        if not role_ids:
            return False

        bot_member = member.guild.me or member.guild.get_member(
            self.bot.user.id if self.bot.user else 0
        )
        if bot_member is None:
            return False

        roles_to_remove = [
            role
            for role in member.roles
            if role.id in role_ids
            and role != member.guild.default_role
            and role < bot_member.top_role
        ]
        if not roles_to_remove:
            return False

        await member.remove_roles(*roles_to_remove, reason=reason)
        return True

    async def _execute_penalty(
        self,
        member: discord.Member,
        penalty: str | None,
        *,
        reason: str,
    ) -> bool:
        action = (penalty or "kick").lower()
        if action == "ban":
            await member.ban(reason=reason)
            return True
        if action == "kick":
            await member.kick(reason=reason)
            return True
        if action == "warn":
            await member.send(f"you were warned in **{member.guild.name}**: {reason}")
            return True
        if action == "jail":
            return await self._confine_member(member, reason=reason)
        return await self._demote_staff(member, reason=reason)

    async def _apply_sanction(
        self,
        member: discord.Member,
        penalty: str | None,
        *,
        reason: str,
    ) -> bool:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            return await self._execute_penalty(member, penalty, reason=reason)
        return False

    async def _evaluate_module_trigger(
        self,
        guild: discord.Guild,
        actor: discord.Member,
        module_name: str,
        *,
        instant: bool = False,
        cmd_detected: bool = False,
        reason: str | None = None,
    ) -> bool:
        config = await self._guild_config(guild.id)
        module = getattr(config, module_name)
        if not module.status:
            return False
        if actor.id in self._bypass_set(guild, config):
            return False
        if cmd_detected and not module.command:
            return False

        limit = None
        used_count: int | None = None
        used_limit: int | None = None
        window_tag: str | None = None
        if not instant:
            await self.db.log_antinuke_action(guild.id, actor.id, module_name)
            short_count = await self.db.get_antinuke_action_count(
                guild.id,
                actor.id,
                module_name,
                SHORT_WINDOW,
            )
            long_count = await self.db.get_antinuke_action_count(
                guild.id,
                actor.id,
                module_name,
                LONG_WINDOW,
            )
            limit = module.threshold
            long_limit = max(limit * LONG_THRESHOLD_FACTOR, limit + 1)
            if short_count < limit and long_count < long_limit:
                return False
            used_count = short_count if short_count >= limit else long_count
            used_limit = limit if short_count >= limit else long_limit
            window_tag = "short" if short_count >= limit else "long"

        base_reason = reason or self._build_reason(module_name, limit)
        auto_reason = base_reason
        if used_count is not None and used_limit is not None and window_tag is not None:
            auto_reason = (
                f"antinuke {module_name}: {base_reason} "
                f"({window_tag} {used_count}/{used_limit})"
            )

        sanctioned = await self._apply_sanction(
            actor,
            module.punishment,
            reason=base_reason,
        )
        if sanctioned:
            auto_action = f"{module.punishment} (auto)"
            case_id = await self._record_case(
                guild,
                action=auto_action,
                target_id=actor.id,
                moderator=self.bot.user or actor,
                reason=auto_reason,
            )
            asyncio.create_task(
                self._dispatch_dm(
                    actor,
                    action=auto_action,
                    guild=guild,
                    moderator=self.bot.user or actor,
                    reason=auto_reason,
                    case_id=case_id,
                )
            )

        lines = [
            "A potential nuke has been detected in your server.",
            (
                f"**{actor}** tripped **{MODULE_NAMES[module_name]}** "
                f"protection and was **{self._owner_verb(module.punishment)}**."
            ),
        ]
        if used_count is not None and used_limit is not None and window_tag is not None:
            lines.append(
                f"Rate: **{used_count}/{used_limit}** ({window_tag})."
            )
        if not sanctioned:
            lines.append("I could not take action due to insufficient permissions.")
        await self._alert_guild_owner(guild, "\n".join(lines))
        return True

    async def _audit_perm_change(
        self,
        guild: discord.Guild,
        actor: discord.Member,
        *,
        change_type: str,
        permissions_changed: set[str],
        label: str,
        revert=None,
    ) -> bool:
        config = await self._guild_config(guild.id)
        if actor.id in self._bypass_set(guild, config):
            return False

        matches = [
            watch
            for watch in config.permissions
            if watch.type == change_type and watch.permission in permissions_changed
        ]
        if not matches:
            return False

        reverted = False
        if revert is not None:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await revert()
                reverted = True

        penalty = self._strongest_penalty(matches)
        reason = f"antinuke permissions: {label}"
        sanctioned = await self._apply_sanction(
            actor,
            penalty,
            reason=reason,
        )
        if sanctioned:
            auto_action = f"{penalty} (auto)"
            case_id = await self._record_case(
                guild,
                action=auto_action,
                target_id=actor.id,
                moderator=self.bot.user or actor,
                reason=reason,
            )
            asyncio.create_task(
                self._dispatch_dm(
                    actor,
                    action=auto_action,
                    guild=guild,
                    moderator=self.bot.user or actor,
                    reason=reason,
                    case_id=case_id,
                )
            )

        lines = [
            "A dangerous permission change was detected in your server.",
            f"**{actor}** {label}.",
            f"They were **{self._owner_verb(penalty)}**.",
        ]
        if revert is not None:
            lines.append(
                "The permission change has been rolled back."
                if reverted
                else "I could not roll back the permission change."
            )
        if not sanctioned:
            lines.append("I could not take action due to insufficient permissions.")
        await self._alert_guild_owner(guild, "\n".join(lines))
        return True

    async def _delete_webhook(
        self,
        channel: discord.abc.GuildChannel,
        target_id: int | None,
    ) -> None:
        if target_id is None:
            return
        fetcher = getattr(channel, "webhooks", None)
        if not callable(fetcher):
            return
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            for webhook in await fetcher():
                if webhook.id == target_id:
                    await webhook.delete(reason="antinuke revert: webhook create")
                    return

    async def _clone_channel(self, channel: discord.abc.GuildChannel) -> None:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            restored = await channel.clone(reason="antinuke revert: channel delete")
            with contextlib.suppress(discord.HTTPException):
                await restored.edit(
                    category=channel.category,
                    position=channel.position,
                    reason="antinuke revert: channel delete",
                )

    async def _recreate_role(self, role: discord.Role) -> None:
        if role.managed:
            return
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            recreated = await role.guild.create_role(
                name=role.name,
                permissions=role.permissions,
                color=role.color,
                hoist=role.hoist,
                mentionable=role.mentionable,
                reason="antinuke revert: role delete",
            )
            with contextlib.suppress(discord.HTTPException):
                await recreated.edit(
                    position=role.position,
                    reason="antinuke revert: role delete",
                )

    async def _rebuild_role(
        self,
        guild: discord.Guild,
        data: dict[str, Any],
    ) -> None:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            recreated = await guild.create_role(
                name=str(data.get("name") or "restored-role"),
                permissions=discord.Permissions(int(data.get("permissions") or 0)),
                color=discord.Color(int(data.get("color") or 0)),
                hoist=bool(data.get("hoist", False)),
                mentionable=bool(data.get("mentionable", False)),
                reason="antinuke revert: role delete",
            )
            with contextlib.suppress(discord.HTTPException):
                await recreated.edit(
                    position=int(data.get("position") or 1),
                    reason="antinuke revert: role delete",
                )

    async def _eject_bot(self, member: discord.Member, penalty: str) -> bool:
        action = "ban" if penalty == "ban" else "kick"
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            if action == "ban":
                await member.ban(reason="antinuke: bot add")
            else:
                await member.kick(reason="antinuke: bot add")
            return True
        return False

    @Package.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        entry = await self._fetch_latest_log(
            guild,
            discord.AuditLogAction.ban,
            target_id=user.id,
        )
        actor = await self._entry_user(guild, entry)
        if actor is None:
            return
        if self._is_recent_cmd_action(guild.id, actor.id, "ban", user.id):
            return
        await self._evaluate_module_trigger(
            guild,
            actor,
            "ban",
            reason="antinuke triggered: ban",
        )

    @Package.listener()
    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        entry = await self._fetch_latest_log(
            guild,
            discord.AuditLogAction.kick,
            target_id=payload.user.id,
        )
        actor = await self._entry_user(guild, entry)
        if actor is None:
            return
        if self._is_recent_cmd_action(guild.id, actor.id, "kick", payload.user.id):
            return
        await self._evaluate_module_trigger(
            guild,
            actor,
            "kick",
            reason="antinuke triggered: kick",
        )

    @Package.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        entry = await self._fetch_latest_log(
            channel.guild,
            discord.AuditLogAction.channel_create,
            target_id=channel.id,
        )
        actor = await self._entry_user(channel.guild, entry)
        if actor is None:
            return
        if await self._evaluate_module_trigger(
            channel.guild,
            actor,
            "channel",
            reason="antinuke triggered: channel create",
        ):
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await channel.delete(reason="antinuke revert: channel create")

    @Package.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        entry = await self._fetch_latest_log(
            channel.guild,
            discord.AuditLogAction.channel_delete,
            target_id=channel.id,
        )
        actor = await self._entry_user(channel.guild, entry)
        if actor is None:
            return
        if await self._evaluate_module_trigger(
            channel.guild,
            actor,
            "channel",
            reason="antinuke triggered: channel delete",
        ):
            await self._clone_channel(channel)

    @Package.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        entry = await self._fetch_latest_log(
            role.guild,
            discord.AuditLogAction.role_delete,
            target_id=role.id,
        )
        actor = await self._entry_user(role.guild, entry)
        if actor is None:
            return
        if self._is_recent_cmd_action(role.guild.id, actor.id, "role", role.id):
            return
        if await self._evaluate_module_trigger(
            role.guild,
            actor,
            "role",
            reason="antinuke triggered: role delete",
        ):
            await self._recreate_role(role)

    @Package.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        if len(before) <= len(after):
            return
        entry = await self._fetch_latest_log(guild, discord.AuditLogAction.emoji_delete)
        actor = await self._entry_user(guild, entry)
        if actor is None:
            return
        await self._evaluate_module_trigger(
            guild,
            actor,
            "emoji",
            reason="antinuke triggered: emoji delete",
        )

    @Package.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        entry = await self._fetch_latest_log(
            channel.guild,
            discord.AuditLogAction.webhook_create,
        )
        actor = await self._entry_user(channel.guild, entry)
        if actor is None:
            return
        if await self._evaluate_module_trigger(
            channel.guild,
            actor,
            "webhook",
            reason="antinuke triggered: webhook create",
        ):
            await self._delete_webhook(channel, getattr(entry.target, "id", None))

    @Package.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        if before.vanity_url_code == after.vanity_url_code:
            return
        entry = await self._fetch_latest_log(after, discord.AuditLogAction.guild_update)
        actor = await self._entry_user(after, entry)
        if actor is None:
            return
        await self._evaluate_module_trigger(
            after,
            actor,
            "vanity",
            instant=True,
            reason="antinuke triggered: vanity update",
        )

    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            return
        config = await self._guild_config(member.guild.id)
        if not config.botadd.status:
            return
        if member.id in set(config.whitelist):
            return

        entry = await self._fetch_latest_log(
            member.guild,
            discord.AuditLogAction.bot_add,
            target_id=member.id,
        )
        actor = await self._entry_user(member.guild, entry)

        bot_action = "ban" if config.botadd.punishment == "ban" else "kick"
        removed = await self._eject_bot(member, bot_action)
        actor_sanctioned = False
        bot_reason = (
            f"antinuke botadd: {member} ({member.id}) added"
            if actor is not None
            else f"antinuke botadd: bot {member.id} added"
        )

        if removed:
            await self._record_case(
                member.guild,
                action=f"{bot_action} (auto)",
                target_id=member.id,
                moderator=self.bot.user or member,
                reason=bot_reason,
            )

        if actor is not None and actor.id not in self._bypass_set(member.guild, config):
            actor_sanctioned = await self._apply_sanction(
                actor,
                config.botadd.punishment,
                reason="antinuke: bot add",
            )
            if actor_sanctioned:
                actor_action = f"{config.botadd.punishment} (auto)"
                actor_case_id = await self._record_case(
                    member.guild,
                    action=actor_action,
                    target_id=actor.id,
                    moderator=self.bot.user or actor,
                    reason=bot_reason,
                )
                asyncio.create_task(
                    self._dispatch_dm(
                        actor,
                        action=actor_action,
                        guild=member.guild,
                        moderator=self.bot.user or actor,
                        reason=bot_reason,
                        case_id=actor_case_id,
                    )
                )

        lines = [
            "A potential nuke has been detected in your server.",
            f"**{actor or 'Unknown user'}** added **{member}**.",
        ]
        if removed:
            lines.append(f"The bot was **{self._penalty_verb(bot_action)}**.")
        else:
            lines.append("I could not remove the new bot due to missing permissions.")
        if actor is not None and actor.id not in self._bypass_set(member.guild, config):
            if actor_sanctioned:
                lines.append(
                    f"The inviter was **{self._penalty_verb(config.botadd.punishment)}**."
                )
            else:
                lines.append("I could not punish the inviter due to missing permissions.")
        await self._alert_guild_owner(member.guild, "\n".join(lines))

    @Package.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if before.permissions == after.permissions:
            return

        added_permissions = {
            permission
            for permission in DANGEROUS_PERMISSIONS
            if not getattr(before.permissions, permission, False)
            and getattr(after.permissions, permission, False)
        }
        removed_permissions = {
            permission
            for permission in DANGEROUS_PERMISSIONS
            if getattr(before.permissions, permission, False)
            and not getattr(after.permissions, permission, False)
        }
        if not added_permissions and not removed_permissions:
            return

        entry = await self._fetch_latest_log(
            after.guild,
            discord.AuditLogAction.role_update,
            target_id=after.id,
        )
        actor = await self._entry_user(after.guild, entry)
        if actor is None:
            return

        if added_permissions:
            await self._audit_perm_change(
                after.guild,
                actor,
                change_type="grant",
                permissions_changed=added_permissions,
                label=f"granted dangerous permissions to role **{after.name}**",
                revert=lambda: after.edit(
                    permissions=before.permissions,
                    reason="antinuke revert: role permission grant",
                ),
            )
        if removed_permissions:
            await self._audit_perm_change(
                after.guild,
                actor,
                change_type="remove",
                permissions_changed=removed_permissions,
                label=f"removed dangerous permissions from role **{after.name}**",
                revert=lambda: after.edit(
                    permissions=before.permissions,
                    reason="antinuke revert: role permission remove",
                ),
            )

    @Package.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return

        added_roles = [role for role in after.roles if role not in before.roles]
        removed_roles = [role for role in before.roles if role not in after.roles]

        added_permissions = {
            permission
            for role in added_roles
            for permission in DANGEROUS_PERMISSIONS
            if getattr(role.permissions, permission, False)
        }
        removed_permissions = {
            permission
            for role in removed_roles
            for permission in DANGEROUS_PERMISSIONS
            if getattr(role.permissions, permission, False)
        }
        if not added_permissions and not removed_permissions:
            return

        entry = await self._fetch_latest_log(
            after.guild,
            discord.AuditLogAction.member_role_update,
            target_id=after.id,
        )
        actor = await self._entry_user(after.guild, entry)
        if actor is None:
            return

        if added_permissions:
            dangerous_added_roles = [
                role
                for role in added_roles
                if any(
                    getattr(role.permissions, permission, False)
                    for permission in DANGEROUS_PERMISSIONS
                )
            ]
            await self._audit_perm_change(
                after.guild,
                actor,
                change_type="grant",
                permissions_changed=added_permissions,
                label=f"granted dangerous roles to **{after}**",
                revert=lambda: after.remove_roles(
                    *dangerous_added_roles,
                    reason="antinuke revert: member dangerous role grant",
                ),
            )

        if removed_permissions:
            dangerous_removed_roles = [
                role
                for role in removed_roles
                if any(
                    getattr(role.permissions, permission, False)
                    for permission in DANGEROUS_PERMISSIONS
                )
            ]
            await self._audit_perm_change(
                after.guild,
                actor,
                change_type="remove",
                permissions_changed=removed_permissions,
                label=f"removed dangerous roles from **{after}**",
                revert=lambda: after.add_roles(
                    *dangerous_removed_roles,
                    reason="antinuke revert: member dangerous role remove",
                ),
            )

    @Package.listener()
    async def on_antinuke_action(
        self,
        guild: discord.Guild,
        actor: discord.Member,
        action: str,
        case_id: int,
        meta: dict | None = None,
    ) -> None:
        mapping = {
            "ban": "ban",
            "tempban": "ban",
            "softban": "ban",
            "kick": "kick",
            "role delete": "role",
        }
        module = mapping.get(action)
        if module is None:
            return

        triggered = await self._evaluate_module_trigger(
            guild,
            actor,
            module,
            cmd_detected=True,
            reason=f"antinuke triggered: {action}",
        )
        if not triggered or module != "role" or not meta:
            if triggered and meta and meta.get("target_id") and module in {"ban", "kick"}:
                self._note_cmd_action(
                    guild.id,
                    actor.id,
                    module,
                    int(meta["target_id"]),
                )
            return

        if action == "role delete" and meta.get("role"):
            if meta.get("role_id"):
                self._note_cmd_action(guild.id, actor.id, module, int(meta["role_id"]))
            await self._rebuild_role(guild, dict(meta["role"]))

    @group(
        name="antinuke",
        usage="(subcommand) <args>",
        example="ban on --do ban",
        aliases=["an"],
        invoke_without_command=True,
    )
    async def antinuke(self, ctx):
        """Antinuke to protect your server."""
        return await ctx.send_help()

    @antinuke.command(
        name="config",
        aliases=["configuration", "settings"],
    )
    async def antinuke_config(self, ctx):
        """View server configuration for Antinuke."""
        config = await self._guild_config(ctx.guild.id)
        active = config.enabled_count()
        bot_count = 0
        member_count = 0
        all_admins = {ctx.guild.owner_id, *config.admins}

        for uid in config.whitelist:
            obj = self.bot.get_user(uid) or ctx.guild.get_member(uid)
            if obj and obj.bot:
                bot_count += 1
            else:
                member_count += 1

        embed = Embed(
            color=self.color,
            title="Settings",
            description=f"Antinuke is **{'active' if active else 'inactive'}** in this server",
        )
        embed.add_field(
            name="Modules",
            value=(
                f"**Role Deletion:** {self._toggle_icon(config.role.status)}"
                f"\n**Emoji Deletion:** {self._toggle_icon(config.emoji.status)}"
                f"\n**Mass Member Ban:** {self._toggle_icon(config.ban.status)}"
                f"\n**Mass Member Kick:** {self._toggle_icon(config.kick.status)}"
                f"\n**Webhook Creation:** {self._toggle_icon(config.webhook.status)}"
                f"\n**Channel Creation/Deletion:** {self._toggle_icon(config.channel.status)}"
                f"\n**Vanity Change:** {self._toggle_icon(config.vanity.status)}"
            ),
            inline=True,
        )
        embed.add_field(
            name="General",
            value=(
                f"**Super Admins:** {len(all_admins)}"
                f"\n**Whitelisted Bots:** {bot_count}"
                f"\n**Whitelisted Members:** {member_count}"
                f"\n**Protection Modules:** {active} active"
                f"\n**Watch Permission Grant:** {self._count_perms(config, kind='grant')}/{len(DANGEROUS_PERMISSIONS)} perms"
                f"\n**Watch Permission Remove:** {self._count_perms(config, kind='remove')}/{len(DANGEROUS_PERMISSIONS)} perms"
                f"\n**Deny Bot Joins (bot add):** {self._toggle_icon(config.botadd.status)}"
            ),
            inline=True,
        )
        return await ctx.send(embed=embed)

    @antinuke.command(
        name="whitelist",
        usage="(member or bot id)",
        example="593921296224747521",
    )
    async def antinuke_whitelist(self, ctx, *, member: MemberConvert):
        """Whitelist a member from triggering antinuke or a bot to join."""
        whitelist = await self.db.fetchval(
            """
            INSERT INTO antinuke (guild_id, whitelist)
            VALUES ($1, ARRAY[$2]::BIGINT[])
            ON CONFLICT (guild_id) DO UPDATE
            SET whitelist = CASE
                WHEN $2 = ANY(antinuke.whitelist) THEN array_remove(antinuke.whitelist, $2)
                ELSE antinuke.whitelist || ARRAY[$2]::BIGINT[]
            END
            RETURNING whitelist;
            """,
            ctx.guild.id,
            member.id,
        )
        await self._load_config(ctx.guild.id)

        if member.id in (whitelist or []):
            note = "can join" if getattr(member, "bot", False) else "bypasses **antinuke**"
            return await ctx.success(f"**{member}** added to whitelist ({note})")
        return await ctx.success(f"**{member}** removed from whitelist")

    @antinuke.command(
        name="admin",
        usage="(member)",
        example="jonathan",
    )
    async def antinuke_admin(self, ctx, *, member: MemberConvert):
        """Give a member permissions to edit antinuke settings."""
        if getattr(member, "bot", False):
            return await ctx.warn("Bots cannot be **antinuke admins**")
        if member.id == ctx.guild.owner_id:
            return await ctx.warn(
                "The **server owner** already has admin access by default"
            )

        admins = await self.db.fetchval(
            """
            INSERT INTO antinuke (guild_id, admins)
            VALUES ($1, ARRAY[$2]::BIGINT[])
            ON CONFLICT (guild_id) DO UPDATE
            SET admins = CASE
                WHEN $2 = ANY(antinuke.admins) THEN array_remove(antinuke.admins, $2)
                ELSE antinuke.admins || ARRAY[$2]::BIGINT[]
            END
            RETURNING admins;
            """,
            ctx.guild.id,
            member.id,
        )
        await self._load_config(ctx.guild.id)

        if member.id in (admins or []):
            return await ctx.success(
                f"**{member}** promoted to **antinuke admin**"
            )
        return await ctx.success(
            f"**{member}** demoted from **antinuke admin**"
        )

    @antinuke.command(name="admins")
    async def antinuke_admins(self, ctx):
        """View all antinuke admins."""
        config = await self._guild_config(ctx.guild.id)
        admin_ids = [ctx.guild.owner_id, *config.admins]
        seen: set[int] = set()
        deduped = [
            uid for uid in admin_ids if not (uid in seen or seen.add(uid))
        ]
        if not deduped:
            return await ctx.warn("No **antinuke admins** configured")
        return await ctx.paginate(
            Embed(title="Antinuke Admins", color=self.color),
            [f"<@{uid}>" for uid in deduped],
        )

    @antinuke.command(name="list")
    async def antinuke_list(self, ctx):
        """View all enabled modules along with whitelisted members and bots."""
        config = await self._guild_config(ctx.guild.id)
        entries: list[str] = []

        for tag, mod in config.enabled_modules():
            parts = [f"action: {mod.punishment or 'kick'}"]
            if tag in {"botadd", "vanity"}:
                parts.append("limit: N/A")
            else:
                parts.append(f"limit: {mod.threshold}")
            if tag in {"ban", "kick", "role"}:
                parts.append(f"cmd: {'yes' if mod.command else 'no'}")
            entries.append(f"{tag} ({', '.join(parts)})")

        for uid in config.whitelist:
            obj = self.bot.get_user(uid) or ctx.guild.get_member(uid)
            label = str(obj) if obj else "Unknown User"
            tag = "BOT" if obj and obj.bot else ("UNKNOWN" if obj is None else "MEMBER")
            entries.append(f"{label} ({uid}) [{tag}]")

        if not entries:
            return await ctx.warn("No **antinuke modules** are currently active")
        width = max(2, len(str(len(entries))))
        numbered = [
            f"{idx:0{width}d} {entry}" for idx, entry in enumerate(entries, start=1)
        ]
        embed = Embed(title="Antinuke modules & whitelist", color=self.color).set_author(
            name=str(ctx.author),
            icon_url=ctx.author.display_avatar.url,
        )
        return await ctx.paginate(
            embed,
            numbered,
        )

    @antinuke.command(
        name="vanity",
        aliases=["vanityurl"],
        usage="(on or off) --params",
        example="on --do ban",
        flags=AntiNukeFlags,
    )
    async def antinuke_vanity(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent vanity URL changes."""
        return await self._adjust_module(ctx, "vanity", status)

    @antinuke.command(
        name="botadd",
        usage="(on or off) --params",
        example="on --do ban",
        flags=AntiNukeFlags,
    )
    async def antinuke_botadd(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent new bot additions."""
        return await self._adjust_module(ctx, "botadd", status)

    @antinuke.command(
        name="webhook",
        usage="(on or off) --params",
        example="on --do ban --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_webhook(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass webhook creation."""
        return await self._adjust_module(ctx, "webhook", status, with_threshold=True)

    @antinuke.command(
        name="emoji",
        usage="(on or off) --params",
        example="on --do kick --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_emoji(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass emoji delete."""
        return await self._adjust_module(ctx, "emoji", status, with_threshold=True)

    @antinuke.command(
        name="permissions",
        usage="(grant or remove) (permission)",
        example="grant administrator",
        aliases=["perms"],
        flags=AntiNukeFlags,
    )
    async def antinuke_permissions(
        self,
        ctx,
        option: str,
        permission: str,
        *,
        flags: str = None,
    ):
        """Watch for dangerous permissions being granted or removed."""
        option = option.lower()
        if option not in {"grant", "remove"}:
            raise CommandError("option must be `grant` or `remove`")

        normalized = normalize_dangerous_permission(permission)
        if not normalized:
            return await ctx.warn(
                "You passed an **invalid permission name**, please visit the documentation [here](https://docs.bleed.bot/help/commands/antinuke/antinuke-permissions)"
            )

        penalty = str(ctx.flags.get("punishment") or "kick").lower()
        if penalty not in {"ban", "kick", "stripstaff", "warn", "jail"}:
            raise CommandError(
                "punishment must be `ban`, `kick`, `jail`, `warn`, or `stripstaff`"
            )

        entry = PermissionWatch(
            type=option,
            permission=normalized,
            punishment=penalty,
        )
        config = await self._guild_config(ctx.guild.id)
        perms = list(config.permissions)

        toggled_off = False
        for existing in list(perms):
            if existing.as_dict() == entry.as_dict():
                perms.remove(existing)
                toggled_off = True
                break
            if existing.type == entry.type and existing.permission == entry.permission:
                perms.remove(existing)

        payload = [item.as_dict() for item in perms]
        if not toggled_off:
            payload.append(entry.as_dict())

        await self.db.execute(
            """
            INSERT INTO antinuke (guild_id, permissions)
            VALUES ($1, ARRAY(SELECT jsonb_array_elements($2::JSONB)))
            ON CONFLICT (guild_id) DO UPDATE
            SET permissions = EXCLUDED.permissions;
            """,
            ctx.guild.id,
            json.dumps(payload),
        )
        await self._load_config(ctx.guild.id)

        if toggled_off:
            direction = "granting" if option == "grant" else "removal"
            return await ctx.success(
                f"Stopped watching for **{direction} of** `{entry.permission}`"
            )

        direction = "granting" if option == "grant" else "removal"
        return await ctx.success(
            f"Now watching for **{direction} of** `{entry.permission}`. Offenders will be **{entry.punishment}**"
        )

    @antinuke.command(
        name="ban",
        usage="(on or off) --params",
        example="on --do ban --command on",
        flags=AntiNukeFlags,
    )
    async def antinuke_ban(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass member ban."""
        return await self._adjust_module(
            ctx,
            "ban",
            status,
            with_threshold=True,
            with_command=True,
        )

    @antinuke.command(
        name="kick",
        usage="(on or off) --params",
        example="on --do stripstaff --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_kick(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass member kick."""
        return await self._adjust_module(
            ctx,
            "kick",
            status,
            with_threshold=True,
            with_command=True,
        )

    @antinuke.command(
        name="channel",
        usage="(on or off) --params",
        example="on --do ban --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_channel(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass channel create and delete."""
        return await self._adjust_module(ctx, "channel", status, with_threshold=True)

    @antinuke.command(
        name="role",
        usage="(on or off) --params",
        example="on --do ban --threshold 3 --command on",
        flags=AntiNukeFlags,
    )
    async def antinuke_role(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass role delete."""
        return await self._adjust_module(
            ctx,
            "role",
            status,
            with_threshold=True,
            with_command=True,
        )

    @antinuke.command(
        name="enable",
        usage="[--recommended]",
        example="--recommended",
        flags=EnableFlags,
    )
    async def antinuke_enable(self, ctx, *, flags: str = None):
        """Enable all antinuke modules."""
        recommended = ctx.flags.get("recommended")

        if recommended:
            defaults = {
                "ban":     {"punishment": "ban", "threshold": 3, "command": True},
                "kick":    {"punishment": "kick", "threshold": 3, "command": True},
                "channel": {"punishment": "ban", "threshold": 3},
                "role":    {"punishment": "ban", "threshold": 3, "command": True},
                "webhook": {"punishment": "ban", "threshold": 3},
                "emoji":   {"punishment": "kick", "threshold": 3},
                "vanity":  {"punishment": "ban"},
                "botadd":  {"punishment": "ban"},
            }
            for module, payload in defaults.items():
                await self._commit_module(ctx.guild.id, module, {**payload, "status": True})
            await self._load_config(ctx.guild.id)
            return await ctx.success(
                "Antinuke is now **fully enabled** with **recommended settings**.\n"
                "All modules active with balanced punishments and thresholds."
            )

        modules = ["ban", "kick", "channel", "role", "webhook", "emoji", "vanity", "botadd"]
        config = await self._guild_config(ctx.guild.id)
        for module in modules:
            cfg = getattr(config, module)
            if not cfg.status:
                payload = {
                    "status": True,
                    "punishment": getattr(cfg, "punishment", "kick"),
                    "threshold": getattr(cfg, "threshold", 3),
                    "command": getattr(cfg, "command", False),
                }
                await self._commit_module(ctx.guild.id, module, payload)
        await self._load_config(ctx.guild.id)
        return await ctx.success("All **antinuke modules** are now **enabled**.")

    @antinuke.command(
        name="disable",
        usage="",
    )
    async def antinuke_disable(self, ctx):
        """Disable all antinuke modules."""
        modules = ["ban", "kick", "channel", "role", "webhook", "emoji", "vanity", "botadd"]
        for module in modules:
            await self._commit_module(ctx.guild.id, module, {"status": False, "punishment": "kick"})
        await self._load_config(ctx.guild.id)
        return await ctx.success("All **antinuke modules** are now **disabled**.")

    @antinuke.command(
        name="reset",
        usage="",
    )
    async def antinuke_reset(self, ctx):
        """Reset all antinuke configuration for this server."""
        await self.bot.db.execute(
            "DELETE FROM antinuke WHERE guild_id = $1",
            ctx.guild.id,
        )
        await self.bot.db.execute(
            "DELETE FROM antinuke_actions WHERE guild_id = $1",
            ctx.guild.id,
        )
        self._config = None
        return await ctx.success("Antinuke configuration has been **reset**.")


async def setup(bot) -> None:
    await bot.add_cog(Antinuke(bot))
