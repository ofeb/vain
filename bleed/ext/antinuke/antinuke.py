from __future__ import annotations

import contextlib
import json
from typing import Any

import discord
from discord import Embed
from discord.ext import commands, tasks
from discord.ext.commands import CommandError, group

from core.discord.package import Package
from core.tools.convert import MemberConvert, StatusConvert
from core.tools.flags import AntiNukeFlags
from core.tools.permissions import DANGEROUS_PERMISSIONS, normalize_dangerous_permission
from core.tools.ratelimit import ratelimiter

from .models import AntinukeConfig, PermissionWatch

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
        if punishment not in {"ban", "kick", "stripstaff"}:
            raise CommandError("punishment must be `ban`, `kick`, or `stripstaff`")

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

    async def _punish_actor(
        self,
        member: discord.Member,
        punishment: str | None,
        *,
        reason: str,
    ) -> None:
        action = (punishment or "kick").lower()
        if action == "ban":
            await member.ban(reason=reason)
            return
        if action == "kick":
            await member.kick(reason=reason)
            return

        roles = [
            role
            for role in member.roles
            if role != member.guild.default_role
            and any(getattr(role.permissions, permission, False) for permission in DANGEROUS_PERMISSIONS)
        ]
        if roles:
            await member.remove_roles(*roles, reason=reason)
            return
        await member.kick(reason=f"{reason} (no staff roles to strip)")

    async def _resolve_actor(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        if member := guild.get_member(user_id):
            return member
        with contextlib.suppress(discord.HTTPException):
            return await guild.fetch_member(user_id)
        return None

    def _permission_rows(self, config: AntinukeConfig, *, kind: str) -> int:
        return config.permission_count(kind)

    @commands.Cog.listener()
    async def on_audit_log_entry_ban(self, entry: discord.AuditLogEntry) -> None:
        config = self.config.get(entry.guild.id)
        if not config or not config.ban.status or not entry.user:
            return

        me = entry.guild.me or entry.guild.get_member(self.bot.user.id if self.bot.user else 0)
        exempt = set(config.whitelist)
        exempt.update(config.admins)
        exempt.add(entry.guild.owner_id)
        if me:
            exempt.add(me.id)

        if entry.user.id in exempt:
            return

        if not ratelimiter(
            bucket=f"antinuke:ban:{entry.guild.id}",
            key=entry.user.id,
            rate=config.ban.threshold,
            per=9,
        ):
            return

        if not (member := await self._resolve_actor(entry.guild, entry.user.id)):
            return

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self._punish_actor(
                member,
                config.ban.punishment,
                reason=f"antinuke: banned X/{config.ban.threshold} in 9 seconds",
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
        if punishment not in {"ban", "kick", "stripstaff"}:
            raise CommandError("punishment must be `ban`, `kick`, or `stripstaff`")

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
