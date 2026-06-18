from __future__ import annotations

import contextlib
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord import Embed
from discord.ext import commands
from discord.ext.commands import CommandError, group, has_permissions

from core.discord.package import Package
from core.tools.convert import MemberConvert, StatusConvert
from core.tools.flags import AntiRaidFlags

from .models import AntiraidConfig, ModuleConfig

MASSJOIN_WINDOW_SECONDS = 10


class Antiraid(Package):
    """antiraid configuration and enforcement."""

    def __init__(self, bot):
        super().__init__(bot)
        self.config: dict[int, AntiraidConfig] = {}
        self.joins: dict[int, deque[tuple[datetime, int]]] = defaultdict(deque)

    async def _refresh_config(self, guild_id: int) -> AntiraidConfig:
        config_row, module_rows = await self.db.fetchrow(
            "SELECT raid_active, punish_until FROM antiraid_config WHERE guild_id = $1",
            guild_id,
            cached=False,
        ), await self.db.fetch_antiraid_modules(guild_id)
        config = AntiraidConfig.from_records(config_row, module_rows)
        self.config[guild_id] = config
        return config

    async def _get_config(self, guild_id: int) -> AntiraidConfig:
        if config := self.config.get(guild_id):
            return config
        return await self._refresh_config(guild_id)

    async def _set_raid_state(self, guild_id: int, active: bool) -> AntiraidConfig:
        await self.db.set_antiraid_state(guild_id, active)
        config = await self._get_config(guild_id)
        config.raid_active = active
        self.config[guild_id] = config
        return config

    async def _set_punish_until(
        self,
        guild_id: int,
        until: datetime | None,
    ) -> AntiraidConfig:
        await self.db.set_antiraid_punish_until(guild_id, until)
        config = await self._get_config(guild_id)
        config.punish_until = until
        self.config[guild_id] = config
        return config

    async def _save_module(
        self,
        guild_id: int,
        module: str,
        *,
        enabled: bool,
        threshold: int | None = None,
        action: str | None = None,
        lock_channels: bool | None = None,
        punish_new: bool | None = None,
    ) -> AntiraidConfig:
        await self.db.upsert_antiraid_module(
            guild_id,
            module,
            enabled=enabled,
            threshold=threshold,
            action=action,
            lock_channels=lock_channels,
            punish_new=punish_new,
        )
        return await self._refresh_config(guild_id)

    def _emoji(self, enabled: bool) -> str:
        if enabled:
            return self.bot.config.get("emojis", {}).get("success", "✅")
        return self.bot.config.get("emojis", {}).get("fail", "❌")

    def _module_summary(self, module: str, config: ModuleConfig) -> str:
        if not config.enabled:
            return f"{self._emoji(False)} disabled"

        if module == "massjoin":
            return (
                f"{self._emoji(True)} do: **{config.action or 'ban'}**"
                f" | threshold: **{config.threshold}**"
                f" | lock: **{'true' if config.lock_channels else 'false'}**"
                f" | punish: **{'true' if config.punish_new else 'false'}**"
            )

        if module == "newaccounts":
            return (
                f"{self._emoji(True)} do: **{config.action or 'ban'}**"
                f" | threshold: **{config.threshold}** days"
            )

        return f"{self._emoji(True)} do: **{config.action or 'kick'}**"

    def _coerce_action(self, action: str | None, *, default: str) -> str:
        value = (action or default).lower()
        if value not in {"ban", "kick"}:
            raise CommandError("punishment must be `ban` or `kick`")
        return value

    async def _punish_member(
        self,
        member: discord.Member,
        action: str,
        *,
        reason: str,
    ) -> None:
        if action == "ban":
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await member.ban(delete_message_seconds=0, reason=reason)
            return

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await member.kick(reason=reason)

    async def _resolve_member(
        self,
        guild: discord.Guild,
        user_id: int,
    ) -> discord.Member | None:
        if member := guild.get_member(user_id):
            return member
        with contextlib.suppress(discord.HTTPException):
            return await guild.fetch_member(user_id)
        return None

    async def _lock_channels(self, guild: discord.Guild) -> int:
        default_role = guild.default_role
        locked = 0
        for channel in guild.text_channels:
            overwrite = channel.overwrites_for(default_role)
            if overwrite.send_messages is False:
                continue

            overwrite.send_messages = False
            try:
                await channel.set_permissions(
                    default_role,
                    overwrite=overwrite,
                    reason="antiraid: raid state enabled",
                )
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

            await self.db.add_antiraid_locked_channel(guild.id, channel.id)
            locked += 1

        return locked

    async def _unlock_channels(self, guild: discord.Guild) -> int:
        default_role = guild.default_role
        unlocked = 0
        for channel_id in await self.db.fetch_antiraid_locked_channels(guild.id):
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            overwrite = channel.overwrites_for(default_role)
            if overwrite.send_messages is not False:
                continue

            overwrite.send_messages = None
            try:
                await channel.set_permissions(
                    default_role,
                    overwrite=overwrite,
                    reason="antiraid: raid state disabled",
                )
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

            unlocked += 1

        await self.db.clear_antiraid_locked_channels(guild.id)
        return unlocked

    async def _massjoin_members(
        self,
        guild: discord.Guild,
        queue: deque[tuple[datetime, int]],
    ) -> list[discord.Member]:
        members: list[discord.Member] = []
        for _, user_id in list(queue):
            if member := await self._resolve_member(guild, user_id):
                members.append(member)
        return members

    @group(
        name="antiraid",
        usage="(subcommand)",
        example="massjoin on --threshold 5 --do ban --lock true --punish true",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def antiraid(self, ctx):
        """Configure protection against targeted bot raids."""
        return await ctx.send_help()

    @antiraid.command(
        name="config",
        aliases=["configuration"],
    )
    @has_permissions(manage_guild=True)
    async def antiraid_config(self, ctx):
        """View the current antiraid configuration."""
        config = await self._get_config(ctx.guild.id)
        whitelist = await self.db.fetch_antiraid_whitelist(ctx.guild.id)
        locked = await self.db.fetch_antiraid_locked_channels(ctx.guild.id)

        punish_window = "inactive"
        if config.punish_until and config.punish_until > datetime.now(timezone.utc):
            punish_window = f"<t:{int(config.punish_until.timestamp())}:R>"

        embed = Embed(
            color=self.color,
            title="Antiraid settings",
            description=f"Current raid state: **{'active' if config.raid_active else 'safe'}**",
        )
        embed.add_field(
            name="Modules",
            value=(
                f"**Mass Joins:** {self._module_summary('massjoin', config.massjoin)}"
                f"\n**Avatar:** {self._module_summary('avatar', config.avatar)}"
                f"\n**New Accounts:** {self._module_summary('newaccounts', config.newaccounts)}"
            ),
            inline=False,
        )
        embed.add_field(
            name="General",
            value=(
                f"**Punish Window:** {punish_window}"
                f"\n**Whitelisted Users:** {len(whitelist)}"
                f"\n**Locked Channels:** {len(locked)}"
            ),
            inline=False,
        )
        return await ctx.send(embed=embed)

    @antiraid.command(
        name="state",
        aliases=["raidstate", "removeraid"],
    )
    @has_permissions(manage_guild=True)
    async def antiraid_state(self, ctx):
        """Disable the current raid state and unlock any antiraid-locked channels."""
        unlocked = await self._unlock_channels(ctx.guild)
        await self._set_raid_state(ctx.guild.id, False)
        await self._set_punish_until(ctx.guild.id, None)
        self.joins.pop(ctx.guild.id, None)

        if unlocked:
            return await ctx.success(
                f"Disabled **raid state** and unlocked **{unlocked}** channel{'s' if unlocked != 1 else ''}"
            )
        return await ctx.success("Disabled **raid state**")

    @antiraid.group(
        name="whitelist",
        usage="(member or user id)",
        example="593921296224747521",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def antiraid_whitelist(self, ctx, *, member: MemberConvert = None):
        """Create or remove a one-time whitelist entry for a join."""
        if member is None:
            return await ctx.send_help()

        added = await self.db.toggle_antiraid_whitelist(ctx.guild.id, member.id)
        if added:
            return await ctx.success(f"**{member}** can now bypass **antiraid** once")
        return await ctx.success(f"Removed **{member}** from the **antiraid** whitelist")

    @antiraid_whitelist.command(name="view", aliases=["list"])
    @has_permissions(manage_guild=True)
    async def antiraid_whitelist_view(self, ctx):
        """View all current one-time antiraid whitelist entries."""
        rows = await self.db.fetch_antiraid_whitelist(ctx.guild.id)
        if not rows:
            return await ctx.warn("There are no **antiraid whitelist** entries")

        lines = [f"<@{row.user_id}> (`{row.user_id}`)" for row in rows]
        return await ctx.paginate(
            Embed(title="Antiraid whitelist", color=self.color),
            lines,
        )

    @antiraid.command(
        name="massjoin",
        usage="(on or off) --params",
        example="on --threshold 5 --do ban --lock true --punish true",
        flags=AntiRaidFlags,
    )
    @has_permissions(manage_guild=True)
    async def antiraid_massjoin(self, ctx, status: StatusConvert, *, flags: str = None):
        """Protect the server against mass joins."""
        if not status:
            await self._save_module(ctx.guild.id, "massjoin", enabled=False)
            return await ctx.success("Disabled **massjoin** antiraid")

        current = (await self._get_config(ctx.guild.id)).massjoin
        threshold = ctx.flags.get("threshold")
        if threshold is None:
            threshold = current.threshold or 5
        threshold = int(threshold)
        if threshold < 1 or threshold > 100:
            raise CommandError("threshold must be between **1** and **100**")

        action = self._coerce_action(
            ctx.flags.get("punishment") or current.action,
            default="ban",
        )
        lock_channels = current.lock_channels if ctx.flags.get("lock") is None else bool(ctx.flags.get("lock"))
        punish_new = current.punish_new if ctx.flags.get("punish") is None else bool(ctx.flags.get("punish"))

        await self._save_module(
            ctx.guild.id,
            "massjoin",
            enabled=True,
            threshold=threshold,
            action=action,
            lock_channels=lock_channels,
            punish_new=punish_new,
        )
        return await ctx.success(
            "Updated **massjoin** antiraid.\n"
            f"Punishment is set to **{action}**, threshold is set to **{threshold}**, "
            f"lock channels is **{'on' if lock_channels else 'off'}**, and punish new joins is **{'on' if punish_new else 'off'}**"
        )

    @antiraid.command(
        name="avatar",
        usage="(on or off) --params",
        example="on --do kick",
        aliases=["defaultpfp"],
        flags=AntiRaidFlags,
    )
    @has_permissions(manage_guild=True)
    async def antiraid_avatar(self, ctx, status: StatusConvert, *, flags: str = None):
        """Punish accounts that join without a profile picture."""
        if not status:
            await self._save_module(ctx.guild.id, "avatar", enabled=False)
            return await ctx.success("Disabled **avatar** antiraid")

        current = (await self._get_config(ctx.guild.id)).avatar
        action = self._coerce_action(
            ctx.flags.get("punishment") or current.action,
            default="kick",
        )
        await self._save_module(
            ctx.guild.id,
            "avatar",
            enabled=True,
            action=action,
        )
        return await ctx.success(
            f"Updated **avatar** antiraid.\nPunishment is set to **{action}**"
        )

    @antiraid.command(
        name="newaccounts",
        usage="(on or off) --params",
        example="on --threshold 7 --do ban",
        aliases=["age", "newaccount"],
        flags=AntiRaidFlags,
    )
    @has_permissions(manage_guild=True)
    async def antiraid_newaccounts(self, ctx, status: StatusConvert, *, flags: str = None):
        """Punish newly registered accounts that join the server."""
        if not status:
            await self._save_module(ctx.guild.id, "newaccounts", enabled=False)
            return await ctx.success("Disabled **new accounts** antiraid")

        current = (await self._get_config(ctx.guild.id)).newaccounts
        threshold = ctx.flags.get("threshold")
        if threshold is None:
            threshold = current.threshold or 7
        threshold = int(threshold)
        if threshold < 1 or threshold > 365:
            raise CommandError("threshold must be between **1** and **365** days")

        action = self._coerce_action(
            ctx.flags.get("punishment") or current.action,
            default="ban",
        )
        await self._save_module(
            ctx.guild.id,
            "newaccounts",
            enabled=True,
            threshold=threshold,
            action=action,
        )
        return await ctx.success(
            "Updated **new accounts** antiraid.\n"
            f"Punishment is set to **{action}** and the minimum account age is **{threshold}** days"
        )

    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return

        if await self.db.consume_antiraid_whitelist(member.guild.id, member.id):
            return

        now = datetime.now(timezone.utc)
        config = await self._get_config(member.guild.id)
        queue = self.joins[member.guild.id]
        queue.append((now, member.id))
        cutoff = now - timedelta(seconds=MASSJOIN_WINDOW_SECONDS)
        while queue and queue[0][0] < cutoff:
            queue.popleft()

        if config.punish_until and config.punish_until <= now:
            config = await self._set_punish_until(member.guild.id, None)

        if (
            config.raid_active
            and config.massjoin.enabled
            and config.massjoin.punish_new
            and config.punish_until
            and config.punish_until > now
        ):
            await self._punish_member(
                member,
                config.massjoin.action or "ban",
                reason="antiraid: massjoin punish window",
            )
            return

        if config.massjoin.enabled and len(queue) >= config.massjoin.threshold and not config.raid_active:
            await self._set_raid_state(member.guild.id, True)
            if config.massjoin.lock_channels:
                await self._lock_channels(member.guild)
            if config.massjoin.punish_new:
                await self._set_punish_until(
                    member.guild.id,
                    now + timedelta(minutes=10),
                )

            for target in await self._massjoin_members(member.guild, queue):
                await self._punish_member(
                    target,
                    config.massjoin.action or "ban",
                    reason="antiraid: massjoin threshold reached",
                )
            queue.clear()

        if member.bot:
            return

        config = await self._get_config(member.guild.id)
        if config.avatar.enabled and member.avatar is None:
            await self._punish_member(
                member,
                config.avatar.action or "kick",
                reason="antiraid: avatar required",
            )
            return

        if config.newaccounts.enabled:
            age = now - member.created_at
            if age < timedelta(days=config.newaccounts.threshold):
                await self._punish_member(
                    member,
                    config.newaccounts.action or "ban",
                    reason="antiraid: account is too new",
                )


async def setup(bot) -> None:
    await bot.add_cog(Antiraid(bot))
