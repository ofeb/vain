from __future__ import annotations

import discord

from core.discord.package import Package


class AntinukeEvents:
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

