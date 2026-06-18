from __future__ import annotations

import contextlib
import json
from typing import Any, Iterable

import discord
from discord import Embed
from discord.ext import commands, tasks
from discord.ext.commands import CommandError, group

from core.discord.package import Package
from core.tools.convert import MemberConvert, StatusConvert
from core.tools.flags import AntiNukeFlags
from core.tools.permissions import DANGEROUS_PERMISSIONS, normalize_dangerous_permission

from .models import AntinukeConfig, PermissionWatch

ACTION_WINDOW_SECONDS = 9
AUDIT_LOOKBACK_SECONDS = 15

MODULE_LABELS = {
    "botadd": "bot add",
    "webhook": "webhook",
    "emoji": "emoji",
    "ban": "ban",
    "kick": "kick",
    "channel": "channel",
    "role": "role",
    "vanity": "vanity",
}

PUNISHMENT_ORDER = {
    "warn": 1,
    "stripstaff": 2,
    "jail": 3,
    "kick": 4,
    "ban": 5,
}


class Antinuke(Package, commands.Cog):
    """server antinuke configuration and enforcement."""

    def __init__(self, bot):
        super().__init__(bot)
        self.config: dict[int, AntinukeConfig] = {}

    async def cog_load(self) -> None:
        if self.bot.db.pool is not None:
            self.revalidate_config.start()

    async def cog_unload(self) -> None:
        if self.revalidate_config.is_running():
            self.revalidate_config.cancel()

    async def cog_check(self, ctx) -> bool:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")

        if await self.bot.is_owner(ctx.author):
            return True

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
    async def revalidate_config(self) -> None:
        rows = await self.db.fetch("SELECT * FROM antinuke", cached=False)
        self.config = {
            row.guild_id: AntinukeConfig.from_record(row)
            for row in rows
        }

    async def _refresh_config(self, guild_id: int) -> AntinukeConfig:
        row = await self.db.fetchrow(
            "SELECT * FROM antinuke WHERE guild_id = $1",
            guild_id,
            cached=False,
        )
        config = AntinukeConfig.from_record(row)
        if row:
            self.config[guild_id] = config
        else:
            self.config.pop(guild_id, None)
        return config

    async def _get_config(self, guild_id: int) -> AntinukeConfig:
        if config := self.config.get(guild_id):
            return config
        return await self._refresh_config(guild_id)

    def _status_emoji(self, enabled: bool) -> str:
        emojis = self.bot.config.get("emojis", {})
        if enabled:
            return emojis.get("success", "✅")
        return emojis.get("fail", "❌")

    def _format_details(self, details: list[str]) -> str:
        if not details:
            return ""
        if len(details) == 1:
            return details[0]
        return f"{', '.join(details[:-1])} and {details[-1]}"

    def _module_payload(
        self,
        *,
        status: bool,
        include_threshold: bool,
        include_command: bool,
        flags: dict[str, Any],
    ) -> dict[str, Any]:
        punishment = str(flags.get("punishment") or "kick").lower()
        if punishment not in {"ban", "kick", "stripstaff", "warn", "jail"}:
            raise CommandError(
                "punishment must be `ban`, `kick`, `jail`, `warn`, or `stripstaff`"
            )

        payload: dict[str, Any] = {
            "status": status,
            "punishment": punishment,
        }
        if include_threshold:
            threshold = int(flags.get("threshold") or 3)
            if threshold < 1 or threshold > 6:
                raise CommandError("threshold must be between **1** and **6**")
            payload["threshold"] = threshold
        if include_command:
            payload["command"] = bool(flags.get("command"))
        return payload

    async def _save_module(self, guild_id: int, name: str, payload: dict[str, Any]) -> None:
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
        await self._refresh_config(guild_id)

    async def _update_module(
        self,
        ctx,
        name: str,
        status: bool,
        *,
        include_threshold: bool = False,
        include_command: bool = False,
    ):
        payload = self._module_payload(
            status=status,
            include_threshold=include_threshold,
            include_command=include_command,
            flags=ctx.flags,
        )
        await self._save_module(ctx.guild.id, name, payload)

        label = MODULE_LABELS[name]
        if not status:
            return await ctx.success(f"Disabled **{label}** antinuke module")

        details = [f"Punishment is set to **{payload['punishment']}**"]
        if include_threshold:
            details.append(f"threshold is set to **{payload['threshold']}**")
        if include_command:
            details.append(
                f"command detection is **{'on' if payload['command'] else 'off'}**"
            )
        return await ctx.success(
            f"Updated **{label}** antinuke module.\n{self._format_details(details)}"
        )

    def _permission_rows(self, config: AntinukeConfig, *, kind: str) -> int:
        return config.permission_count(kind)

    def _module_reason(self, module_name: str, threshold: int | None = None) -> str:
        if threshold:
            return (
                f"antinuke: triggered {module_name} "
                f"X/{threshold} in {ACTION_WINDOW_SECONDS} seconds"
            )
        return f"antinuke: triggered {module_name}"

    def _punishment_label(self, punishment: str | None) -> str:
        mapping = {
            "ban": "banned",
            "kick": "kicked",
            "jail": "jailed",
            "stripstaff": "stripped of staff",
            "warn": "warned",
        }
        return mapping.get((punishment or "kick").lower(), "punished")

    def _pick_permission_punishment(self, matches: Iterable[PermissionWatch]) -> str:
        ordered = sorted(
            matches,
            key=lambda item: PUNISHMENT_ORDER.get(item.punishment, 0),
            reverse=True,
        )
        if not ordered:
            return "kick"
        return ordered[0].punishment

    def _exempt_ids(self, guild: discord.Guild, config: AntinukeConfig) -> set[int]:
        ids = set(config.whitelist)
        ids.update(config.admins)
        ids.add(guild.owner_id)
        if self.bot.user:
            ids.add(self.bot.user.id)
        me = guild.me or guild.get_member(self.bot.user.id if self.bot.user else 0)
        if me:
            ids.add(me.id)
        return ids

    async def _resolve_actor(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        if member := guild.get_member(user_id):
            return member
        with contextlib.suppress(discord.HTTPException):
            return await guild.fetch_member(user_id)
        return None

    async def _audit_actor(
        self,
        guild: discord.Guild,
        entry: discord.AuditLogEntry | None,
    ) -> discord.Member | None:
        if not entry or not entry.user:
            return None
        if isinstance(entry.user, discord.Member):
            return entry.user
        return await self._resolve_actor(guild, entry.user.id)

    async def _latest_audit(
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
                if age > AUDIT_LOOKBACK_SECONDS:
                    continue
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                return entry
        return None

    async def _notify_owner(self, guild: discord.Guild, description: str) -> None:
        owner = guild.owner
        if owner is None:
            with contextlib.suppress(discord.HTTPException):
                owner = await guild.fetch_member(guild.owner_id)
        if owner is None and self.bot.user:
            with contextlib.suppress(discord.HTTPException):
                owner = await self.bot.fetch_user(guild.owner_id)
        if owner is None:
            return
        embed = Embed(color=self.color, description=description)
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await owner.send(embed=embed)

    async def _jail_actor(
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

    async def _punish_actor(
        self,
        member: discord.Member,
        punishment: str | None,
        *,
        reason: str,
    ) -> bool:
        action = (punishment or "kick").lower()
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
            return await self._jail_actor(member, reason=reason)

        dangerous_roles = [
            role
            for role in member.roles
            if role != member.guild.default_role
            and any(
                getattr(role.permissions, permission, False)
                for permission in DANGEROUS_PERMISSIONS
            )
        ]
        if dangerous_roles:
            await member.remove_roles(*dangerous_roles, reason=reason)
            return True
        await member.kick(reason=f"{reason} (no staff roles to strip)")
        return True

    async def _apply_punishment(
        self,
        member: discord.Member,
        punishment: str | None,
        *,
        reason: str,
    ) -> bool:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            return await self._punish_actor(member, punishment, reason=reason)
        return False

    async def _handle_module_action(
        self,
        guild: discord.Guild,
        actor: discord.Member,
        module_name: str,
        *,
        immediate: bool = False,
    ) -> bool:
        config = await self._get_config(guild.id)
        module = getattr(config, module_name)
        if not module.status:
            return False
        if actor.id in self._exempt_ids(guild, config):
            return False

        threshold = None
        if not immediate:
            await self.db.log_antinuke_action(guild.id, actor.id, module_name)
            count = await self.db.get_antinuke_action_count(
                guild.id,
                actor.id,
                module_name,
                ACTION_WINDOW_SECONDS,
            )
            threshold = module.threshold
            if count < threshold:
                return False

        punished = await self._apply_punishment(
            actor,
            module.punishment,
            reason=self._module_reason(module_name, threshold),
        )

        description = [
            "A potential nuke has been detected in your server.",
            (
                f"**{actor}** triggered **{MODULE_LABELS[module_name]}** "
                f"antinuke and was **{self._punishment_label(module.punishment)}**."
            ),
        ]
        if threshold:
            description.append(
                f"Threshold: **{threshold}** action(s) in **{ACTION_WINDOW_SECONDS} seconds**."
            )
        if not punished:
            description.append("I could not punish them due to missing permissions.")
        await self._notify_owner(guild, "\n".join(description))
        return True

    async def _handle_permission_change(
        self,
        guild: discord.Guild,
        actor: discord.Member,
        *,
        change_type: str,
        changed_permissions: set[str],
        label: str,
        revert=None,
    ) -> bool:
        config = await self._get_config(guild.id)
        if actor.id in self._exempt_ids(guild, config):
            return False

        matches = [
            watch
            for watch in config.permissions
            if watch.type == change_type and watch.permission in changed_permissions
        ]
        if not matches:
            return False

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            if revert is not None:
                await revert()

        punishment = self._pick_permission_punishment(matches)
        punished = await self._apply_punishment(
            actor,
            punishment,
            reason=f"antinuke: {label}",
        )

        description = [
            "A dangerous permission change was detected in your server.",
            f"**{actor}** {label}.",
            f"They were **{self._punishment_label(punishment)}**.",
        ]
        if not punished:
            description.append("I could not punish them due to missing permissions.")
        await self._notify_owner(guild, "\n".join(description))
        return True

    async def _remove_created_webhook(
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

    async def _restore_deleted_channel(self, channel: discord.abc.GuildChannel) -> None:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            restored = await channel.clone(reason="antinuke revert: channel delete")
            with contextlib.suppress(discord.HTTPException):
                await restored.edit(
                    category=channel.category,
                    position=channel.position,
                    reason="antinuke revert: channel delete",
                )

    async def _restore_deleted_role(self, role: discord.Role) -> None:
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

    async def _remove_joined_bot(self, member: discord.Member, punishment: str) -> bool:
        action = "ban" if punishment == "ban" else "kick"
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            if action == "ban":
                await member.ban(reason="antinuke: bot add")
            else:
                await member.kick(reason="antinuke: bot add")
            return True
        return False

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        entry = await self._latest_audit(
            guild,
            discord.AuditLogAction.ban,
            target_id=user.id,
        )
        actor = await self._audit_actor(guild, entry)
        if actor is None:
            return
        await self._handle_module_action(guild, actor, "ban")

    @commands.Cog.listener()
    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        entry = await self._latest_audit(
            guild,
            discord.AuditLogAction.kick,
            target_id=payload.user.id,
        )
        actor = await self._audit_actor(guild, entry)
        if actor is None:
            return
        await self._handle_module_action(guild, actor, "kick")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        entry = await self._latest_audit(
            channel.guild,
            discord.AuditLogAction.channel_create,
            target_id=channel.id,
        )
        actor = await self._audit_actor(channel.guild, entry)
        if actor is None:
            return
        if await self._handle_module_action(channel.guild, actor, "channel"):
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await channel.delete(reason="antinuke revert: channel create")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        entry = await self._latest_audit(
            channel.guild,
            discord.AuditLogAction.channel_delete,
            target_id=channel.id,
        )
        actor = await self._audit_actor(channel.guild, entry)
        if actor is None:
            return
        if await self._handle_module_action(channel.guild, actor, "channel"):
            await self._restore_deleted_channel(channel)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        entry = await self._latest_audit(
            role.guild,
            discord.AuditLogAction.role_create,
            target_id=role.id,
        )
        actor = await self._audit_actor(role.guild, entry)
        if actor is None:
            return
        if await self._handle_module_action(role.guild, actor, "role"):
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await role.delete(reason="antinuke revert: role create")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        entry = await self._latest_audit(
            role.guild,
            discord.AuditLogAction.role_delete,
            target_id=role.id,
        )
        actor = await self._audit_actor(role.guild, entry)
        if actor is None:
            return
        if await self._handle_module_action(role.guild, actor, "role"):
            await self._restore_deleted_role(role)

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        if len(before) <= len(after):
            return
        entry = await self._latest_audit(guild, discord.AuditLogAction.emoji_delete)
        actor = await self._audit_actor(guild, entry)
        if actor is None:
            return
        await self._handle_module_action(guild, actor, "emoji")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        entry = await self._latest_audit(
            channel.guild,
            discord.AuditLogAction.webhook_create,
        )
        actor = await self._audit_actor(channel.guild, entry)
        if actor is None:
            return
        if await self._handle_module_action(channel.guild, actor, "webhook"):
            await self._remove_created_webhook(channel, getattr(entry.target, "id", None))

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        if before.vanity_url_code == after.vanity_url_code:
            return
        entry = await self._latest_audit(after, discord.AuditLogAction.guild_update)
        actor = await self._audit_actor(after, entry)
        if actor is None:
            return
        await self._handle_module_action(after, actor, "vanity", immediate=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            return
        config = await self._get_config(member.guild.id)
        if not config.botadd.status:
            return
        if member.id in set(config.whitelist):
            return

        entry = await self._latest_audit(
            member.guild,
            discord.AuditLogAction.bot_add,
            target_id=member.id,
        )
        actor = await self._audit_actor(member.guild, entry)

        bot_action = "ban" if config.botadd.punishment == "ban" else "kick"
        removed = await self._remove_joined_bot(member, bot_action)
        actor_punished = False

        if actor is not None and actor.id not in self._exempt_ids(member.guild, config):
            actor_punished = await self._apply_punishment(
                actor,
                config.botadd.punishment,
                reason="antinuke: bot add",
            )

        description = [
            "A potential nuke has been detected in your server.",
            f"**{actor or 'Unknown user'}** added **{member}**.",
        ]
        if removed:
            description.append(f"The bot was **{self._punishment_label(bot_action)}**.")
        else:
            description.append("I could not remove the new bot due to missing permissions.")
        if actor is not None and actor.id not in self._exempt_ids(member.guild, config):
            if actor_punished:
                description.append(
                    f"The inviter was **{self._punishment_label(config.botadd.punishment)}**."
                )
            else:
                description.append("I could not punish the inviter due to missing permissions.")
        await self._notify_owner(member.guild, "\n".join(description))

    @commands.Cog.listener()
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

        entry = await self._latest_audit(
            after.guild,
            discord.AuditLogAction.role_update,
            target_id=after.id,
        )
        actor = await self._audit_actor(after.guild, entry)
        if actor is None:
            return

        if added_permissions:
            await self._handle_permission_change(
                after.guild,
                actor,
                change_type="grant",
                changed_permissions=added_permissions,
                label=f"granted dangerous permissions to role **{after.name}**",
                revert=lambda: after.edit(
                    permissions=before.permissions,
                    reason="antinuke revert: role permission grant",
                ),
            )
        if removed_permissions:
            await self._handle_permission_change(
                after.guild,
                actor,
                change_type="remove",
                changed_permissions=removed_permissions,
                label=f"removed dangerous permissions from role **{after.name}**",
                revert=lambda: after.edit(
                    permissions=before.permissions,
                    reason="antinuke revert: role permission remove",
                ),
            )

    @commands.Cog.listener()
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

        entry = await self._latest_audit(
            after.guild,
            discord.AuditLogAction.member_role_update,
            target_id=after.id,
        )
        actor = await self._audit_actor(after.guild, entry)
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
            await self._handle_permission_change(
                after.guild,
                actor,
                change_type="grant",
                changed_permissions=added_permissions,
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
            await self._handle_permission_change(
                after.guild,
                actor,
                change_type="remove",
                changed_permissions=removed_permissions,
                label=f"removed dangerous roles from **{after}**",
                revert=lambda: after.add_roles(
                    *dangerous_removed_roles,
                    reason="antinuke revert: member dangerous role remove",
                ),
            )

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
        config = await self._get_config(ctx.guild.id)
        enabled = config.enabled_count()
        whitelisted_bots = 0
        whitelisted_members = 0

        for user_id in config.whitelist:
            user = self.bot.get_user(user_id) or ctx.guild.get_member(user_id)
            if user and user.bot:
                whitelisted_bots += 1
            else:
                whitelisted_members += 1

        embed = Embed(
            color=self.color,
            title="Settings",
            description=f"Antinuke is **{'enabled' if enabled else 'disabled'}** in this server",
        )
        embed.add_field(
            name="Modules",
            value=(
                f"**Role Deletion:** {self._status_emoji(config.role.status)}"
                f"\n**Emoji Deletion:** {self._status_emoji(config.emoji.status)}"
                f"\n**Mass Member Ban:** {self._status_emoji(config.ban.status)}"
                f"\n**Mass Member Kick:** {self._status_emoji(config.kick.status)}"
                f"\n**Webhook Creation:** {self._status_emoji(config.webhook.status)}"
                f"\n**Channel Creation/Deletion:** {self._status_emoji(config.channel.status)}"
                f"\n**Vanity Change:** {self._status_emoji(config.vanity.status)}"
            ),
            inline=True,
        )
        embed.add_field(
            name="General",
            value=(
                f"**Super Admins:** {len(config.admins)}"
                f"\n**Whitelisted Bots:** {whitelisted_bots}"
                f"\n**Whitelisted Members:** {whitelisted_members}"
                f"\n**Protection Modules:** {enabled} enabled"
                f"\n**Watch Permission Grant:** {self._permission_rows(config, kind='grant')}/{len(DANGEROUS_PERMISSIONS)} perms"
                f"\n**Watch Permission Remove:** {self._permission_rows(config, kind='remove')}/{len(DANGEROUS_PERMISSIONS)} perms"
                f"\n**Deny Bot Joins (bot add):** {self._status_emoji(config.botadd.status)}"
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
        await self._refresh_config(ctx.guild.id)

        if member.id in (whitelist or []):
            action = "can join" if getattr(member, "bot", False) else "will not trigger **antinuke**"
            return await ctx.success(f"**{member}** is now whitelisted and {action}")
        return await ctx.success(f"**{member}** is no longer whitelisted")

    @antinuke.command(
        name="admin",
        usage="(member)",
        example="jonathan",
    )
    async def antinuke_admin(self, ctx, *, member: MemberConvert):
        """Give a member permissions to edit antinuke settings."""
        if getattr(member, "bot", False):
            return await ctx.warn("You cannot make a bot an **antinuke admin**")

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
        await self._refresh_config(ctx.guild.id)

        if member.id in (admins or []):
            return await ctx.success(
                f"**{member}** is now an **antinuke admin** and can edit **antinuke settings**"
            )
        return await ctx.success(
            f"**{member}** is no longer an **antinuke admin** and can no longer edit **antinuke settings**"
        )

    @antinuke.command(name="admins")
    async def antinuke_admins(self, ctx):
        """View all antinuke admins."""
        config = await self._get_config(ctx.guild.id)
        if not config.admins:
            return await ctx.warn("There are no **antinuke admins**")
        return await ctx.paginate(
            Embed(title="Antinuke Admins", color=self.color),
            [f"<@{user_id}>" for user_id in config.admins],
        )

    @antinuke.command(name="list")
    async def antinuke_list(self, ctx):
        """View all enabled modules along with whitelisted members and bots."""
        config = await self._get_config(ctx.guild.id)
        entries: list[str] = []

        for name, module in config.enabled_modules():
            details = [f"do: {module.punishment or 'kick'}"]
            if name not in {"botadd", "vanity"}:
                details.append(f"threshold: {module.threshold}")
            if name in {"ban", "kick", "role"}:
                details.append(f"cmd: {'on' if module.command else 'off'}")
            entries.append(f"**{name}** ({', '.join(details)})")

        for user_id in config.whitelist:
            user = self.bot.get_user(user_id) or ctx.guild.get_member(user_id)
            label = str(user) if user else "Unknown User"
            kind = "BOT" if user and user.bot else ("UNKNOWN" if user is None else "MEMBER")
            entries.append(f"**{label}** whitelisted (`{user_id}`) [`{kind}`]")

        if not entries:
            return await ctx.warn("There are no **antinuke modules** enabled")
        return await ctx.paginate(
            Embed(title="Antinuke modules & whitelist", color=self.color),
            entries,
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
        return await self._update_module(ctx, "vanity", status)

    @antinuke.command(
        name="botadd",
        usage="(on or off) --params",
        example="on --do ban",
        flags=AntiNukeFlags,
    )
    async def antinuke_botadd(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent new bot additions."""
        return await self._update_module(ctx, "botadd", status)

    @antinuke.command(
        name="webhook",
        usage="(on or off) --params",
        example="on --do ban --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_webhook(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass webhook creation."""
        return await self._update_module(ctx, "webhook", status, include_threshold=True)

    @antinuke.command(
        name="emoji",
        usage="(on or off) --params",
        example="on --do kick --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_emoji(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass emoji delete."""
        return await self._update_module(ctx, "emoji", status, include_threshold=True)

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

        punishment = str(ctx.flags.get("punishment") or "kick").lower()
        if punishment not in {"ban", "kick", "stripstaff", "warn", "jail"}:
            raise CommandError(
                "punishment must be `ban`, `kick`, `jail`, `warn`, or `stripstaff`"
            )

        candidate = PermissionWatch(
            type=option,
            permission=normalized,
            punishment=punishment,
        )
        config = await self._get_config(ctx.guild.id)
        permissions = list(config.permissions)

        removed = False
        for existing in list(permissions):
            if existing.as_dict() == candidate.as_dict():
                permissions.remove(existing)
                removed = True
                break
            if existing.type == candidate.type and existing.permission == candidate.permission:
                permissions.remove(existing)

        payload = [item.as_dict() for item in permissions]
        if not removed:
            payload.append(candidate.as_dict())

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
        await self._refresh_config(ctx.guild.id)

        if removed:
            action = "granting" if option == "grant" else "removal"
            return await ctx.success(
                f"No longer monitoring **{action} of** permission `{candidate.permission}`"
            )

        action = "granting" if option == "grant" else "removal"
        return await ctx.success(
            f"Now monitoring **{action} of** permission `{candidate.permission}`. Members **manually** giving out roles to others will be punished with `{candidate.punishment}`"
        )

    @antinuke.command(
        name="ban",
        usage="(on or off) --params",
        example="on --do ban --command on",
        flags=AntiNukeFlags,
    )
    async def antinuke_ban(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass member ban."""
        return await self._update_module(
            ctx,
            "ban",
            status,
            include_threshold=True,
            include_command=True,
        )

    @antinuke.command(
        name="kick",
        usage="(on or off) --params",
        example="on --do stripstaff --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_kick(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass member kick."""
        return await self._update_module(
            ctx,
            "kick",
            status,
            include_threshold=True,
            include_command=True,
        )

    @antinuke.command(
        name="channel",
        usage="(on or off) --params",
        example="on --do ban --threshold 3",
        flags=AntiNukeFlags,
    )
    async def antinuke_channel(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass channel create and delete."""
        return await self._update_module(ctx, "channel", status, include_threshold=True)

    @antinuke.command(
        name="role",
        usage="(on or off) --params",
        example="on --do ban --threshold 3 --command on",
        flags=AntiNukeFlags,
    )
    async def antinuke_role(self, ctx, status: StatusConvert, *, flags: str = None):
        """Prevent mass role delete."""
        return await self._update_module(
            ctx,
            "role",
            status,
            include_threshold=True,
            include_command=True,
        )


async def setup(bot) -> None:
    await bot.add_cog(Antinuke(bot))
