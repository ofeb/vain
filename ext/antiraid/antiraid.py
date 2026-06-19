from __future__ import annotations

import contextlib
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import Embed
from discord.ext import commands
from discord.ext.commands import CommandError, FlagConverter, flag, group

from core.discord.package import Package
from core.tools.convert import MemberConvert, StatusConvert
from core.tools.flags import AntiRaidFlags

from .models import AntiraidConfig, ModuleConfig

from core.managers.permissions import has_permissions
MASSJOIN_WINDOW = 10


class Antiraid(Package):
    """antiraid configuration and enforcement."""

    def __init__(self, bot):
        super().__init__(bot)
        self.config: dict[int, AntiraidConfig] = {}
        self.join_log: dict[int, deque[tuple[datetime, int]]] = defaultdict(deque)

    async def _pull_config(self, guild_id: int) -> AntiraidConfig:
        cr = await self.db.fetchrow(
            "SELECT raid_active, punish_until FROM antiraid_config WHERE guild_id = $1",
            guild_id,
            cached=False,
        )
        mr = await self.db.fetch_antiraid_modules(guild_id)
        cfg = AntiraidConfig.from_records(cr, mr)
        self.config[guild_id] = cfg
        return cfg

    async def _cached_config(self, guild_id: int) -> AntiraidConfig:
        if cfg := self.config.get(guild_id):
            return cfg
        return await self._pull_config(guild_id)

    async def _toggle_raid(self, guild_id: int, active: bool) -> AntiraidConfig:
        await self.db.set_antiraid_state(guild_id, active)
        cfg = await self._cached_config(guild_id)
        cfg.raid_active = active
        self.config[guild_id] = cfg
        return cfg

    async def _set_punish_window(
        self,
        guild_id: int,
        until: datetime | None,
    ) -> AntiraidConfig:
        await self.db.set_antiraid_punish_until(guild_id, until)
        cfg = await self._cached_config(guild_id)
        cfg.punish_until = until
        self.config[guild_id] = cfg
        return cfg

    async def _store_module(
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
        return await self._pull_config(guild_id)

    def _indicator(self, active: bool) -> str:
        emojis = self.bot.config.get("emojis", {})
        return emojis.get("success", "✅") if active else emojis.get("fail", "❌")

    def _describe(self, module: str, cfg: ModuleConfig) -> str:
        if not cfg.enabled:
            return f"{self._indicator(False)} N/A, threshold: N/A"

        if module == "massjoin":
            return (
                f"{self._indicator(True)}"
                f" (do: {cfg.action or 'ban'}, threshold: {cfg.threshold})"
            )

        if module == "newaccounts":
            return (
                f"{self._indicator(True)}"
                f" (do: {cfg.action or 'ban'}, threshold: {cfg.threshold})"
            )

        if module == "avatar":
            return (
                f"{self._indicator(True)}"
                f" (do: {cfg.action or 'kick'}, threshold: N/A)"
            )

        return f"{self._indicator(True)} (do: {cfg.action or 'kick'}, threshold: N/A)"

    def _validate_action(self, action: str | None, *, fallback: str) -> str:
        value = (action or fallback).lower()
        if value not in {"ban", "kick"}:
            raise CommandError("action must be `ban` or `kick`")
        return value

    async def _sanction_member(
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

    async def _locate_member(
        self,
        guild: discord.Guild,
        uid: int,
    ) -> discord.Member | None:
        if member := guild.get_member(uid):
            return member
        with contextlib.suppress(discord.HTTPException):
            return await guild.fetch_member(uid)
        return None

    async def _disable_chat(self, guild: discord.Guild) -> int:
        everyone = guild.default_role
        count = 0
        for ch in guild.text_channels:
            overwrite = ch.overwrites_for(everyone)
            if overwrite.send_messages is False:
                continue

            overwrite.send_messages = False
            try:
                await ch.set_permissions(
                    everyone,
                    overwrite=overwrite,
                    reason="antiraid: raid active",
                )
            except (discord.Forbidden, discord.HTTPException):
                continue

            await self.db.add_antiraid_locked_channel(guild.id, ch.id)
            count += 1

        return count

    async def _enable_chat(self, guild: discord.Guild) -> int:
        everyone = guild.default_role
        count = 0
        for ch_id in await self.db.fetch_antiraid_locked_channels(guild.id):
            ch = guild.get_channel(ch_id)
            if not isinstance(ch, discord.TextChannel):
                continue

            overwrite = ch.overwrites_for(everyone)
            if overwrite.send_messages is not False:
                continue

            overwrite.send_messages = None
            try:
                await ch.set_permissions(
                    everyone,
                    overwrite=overwrite,
                    reason="antiraid: raid over",
                )
            except (discord.Forbidden, discord.HTTPException):
                continue

            count += 1

        await self.db.clear_antiraid_locked_channels(guild.id)
        return count

    async def _build_member_list(
        self,
        guild: discord.Guild,
        queue: deque[tuple[datetime, int]],
    ) -> list[discord.Member]:
        members: list[discord.Member] = []
        for _, uid in list(queue):
            if member := await self._locate_member(guild, uid):
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
        cfg = await self._cached_config(ctx.guild.id)
        wl = await self.db.fetch_antiraid_whitelist(ctx.guild.id)
        locked = await self.db.fetch_antiraid_locked_channels(ctx.guild.id)

        pwin = "inactive"
        if cfg.punish_until and cfg.punish_until > datetime.now(timezone.utc):
            pwin = f"<t:{int(cfg.punish_until.timestamp())}:R>"

        embed = Embed(
            color=self.color,
            title="Antiraid settings",
            description=f"Current Raid State: **{'active' if cfg.raid_active else 'Safe'}**",
        )
        embed.add_field(
            name="Modules",
            value=(
                f"**Punish New Accounts:** {self._describe('newaccounts', cfg.newaccounts)}"
                f"\n**Mass Bot Raids:** {self._describe('massjoin', cfg.massjoin)}"
                f"\n**Punish Default PFPs:** {self._describe('avatar', cfg.avatar)}"
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
        unlocked = await self._enable_chat(ctx.guild)
        await self._toggle_raid(ctx.guild.id, False)
        await self._set_punish_window(ctx.guild.id, None)
        self.join_log.pop(ctx.guild.id, None)

        if unlocked:
            return await ctx.success(
                f"Raid state **ended** and **{unlocked}** channel{'s' if unlocked != 1 else ''} unlocked"
            )
        return await ctx.success("Raid state **ended**")

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
            return await ctx.success(f"**{member}** is now **temporarily** whitelisted and can join")
        return await ctx.success(f"**{member}** is no longer whitelisted")

    @antiraid_whitelist.command(name="view", aliases=["list"])
    @has_permissions(manage_guild=True)
    async def antiraid_whitelist_view(self, ctx):
        """View all current one-time antiraid whitelist entries."""
        rows = await self.db.fetch_antiraid_whitelist(ctx.guild.id)
        if not rows:
            return await ctx.warn("No **antiraid whitelist** entries exist")

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
            await self._store_module(ctx.guild.id, "massjoin", enabled=False)
            return await ctx.success("**massjoin** antiraid turned off")

        current = (await self._cached_config(ctx.guild.id)).massjoin
        threshold = ctx.flags.get("threshold")
        if threshold is None:
            threshold = current.threshold or 5
        threshold = int(threshold)
        if threshold < 1 or threshold > 100:
            raise CommandError("threshold must be between **1** and **100**")

        action = self._validate_action(
            ctx.flags.get("punishment") or current.action,
            fallback="ban",
        )
        lock_channels = current.lock_channels if ctx.flags.get("lock") is None else bool(ctx.flags.get("lock"))
        punish_new = current.punish_new if ctx.flags.get("punish") is None else bool(ctx.flags.get("punish"))

        was_enabled = current.enabled
        await self._store_module(
            ctx.guild.id,
            "massjoin",
            enabled=True,
            threshold=threshold,
            action=action,
            lock_channels=lock_channels,
            punish_new=punish_new,
        )
        verb = "Updated" if was_enabled else "Enabled"
        return await ctx.success(
            f"{verb} **massjoin** antiraid. Punishment set to **{action}** , "
            f"threshold set to {threshold}, "
            f"lock channels set to **{lock_channels}**, "
            f"punish new members set to **{punish_new}**"
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
            await self._store_module(ctx.guild.id, "avatar", enabled=False)
            return await ctx.success("**avatar** antiraid turned off")

        current = (await self._cached_config(ctx.guild.id)).avatar
        action = self._validate_action(
            ctx.flags.get("punishment") or current.action,
            fallback="kick",
        )
        was_enabled = current.enabled
        await self._store_module(
            ctx.guild.id,
            "avatar",
            enabled=True,
            action=action,
        )
        verb = "Updated" if was_enabled else "Enabled"
        return await ctx.success(
            f"{verb} **avatar** antiraid. Punishment set to **{action}**"
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
            await self._store_module(ctx.guild.id, "newaccounts", enabled=False)
            return await ctx.success("**new accounts** antiraid turned off")

        current = (await self._cached_config(ctx.guild.id)).newaccounts
        threshold = ctx.flags.get("threshold")
        if threshold is None:
            threshold = current.threshold or 7
        threshold = int(threshold)
        if threshold < 1 or threshold > 365:
            raise CommandError("threshold must be between **1** and **365** days")

        action = self._validate_action(
            ctx.flags.get("punishment") or current.action,
            fallback="ban",
        )
        was_enabled = current.enabled
        await self._store_module(
            ctx.guild.id,
            "newaccounts",
            enabled=True,
            threshold=threshold,
            action=action,
        )
        verb = "Updated" if was_enabled else "Enabled"
        return await ctx.success(
            f"{verb} **newaccounts** antiraid. Punishment set to **{action}**, threshold set to {threshold}"
        )

    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return

        if await self.db.consume_antiraid_whitelist(member.guild.id, member.id):
            return

        now = datetime.now(timezone.utc)
        cfg = await self._cached_config(member.guild.id)
        log = self.join_log[member.guild.id]
        log.append((now, member.id))
        cutoff = now - timedelta(seconds=MASSJOIN_WINDOW)
        while log and log[0][0] < cutoff:
            log.popleft()

        if cfg.punish_until and cfg.punish_until <= now:
            cfg = await self._set_punish_window(member.guild.id, None)

        if (
            cfg.raid_active
            and cfg.massjoin.enabled
            and cfg.massjoin.punish_new
            and cfg.punish_until
            and cfg.punish_until > now
        ):
            await self._sanction_member(
                member,
                cfg.massjoin.action or "ban",
                reason="antiraid: massjoin window active",
            )
            return

        if cfg.massjoin.enabled and len(log) >= cfg.massjoin.threshold and not cfg.raid_active:
            await self._toggle_raid(member.guild.id, True)
            if cfg.massjoin.lock_channels:
                await self._disable_chat(member.guild)
            if cfg.massjoin.punish_new:
                await self._set_punish_window(
                    member.guild.id,
                    now + timedelta(minutes=10),
                )

            for target in await self._build_member_list(member.guild, log):
                await self._sanction_member(
                    target,
                    cfg.massjoin.action or "ban",
                    reason="antiraid: massjoin limit hit",
                )
            log.clear()

        if member.bot:
            return

        cfg = await self._cached_config(member.guild.id)
        if cfg.avatar.enabled and member.avatar is None:
            await self._sanction_member(
                member,
                cfg.avatar.action or "kick",
                reason="antiraid: no avatar",
            )
            return

        if cfg.newaccounts.enabled:
            age = now - member.created_at
            if age < timedelta(days=cfg.newaccounts.threshold):
                await self._sanction_member(
                    member,
                    cfg.newaccounts.action or "ban",
                    reason="antiraid: account too new",
                )

    @antiraid.command(
        name="enable",
        usage="[--recommended]",
        example="--recommended",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_enable(self, ctx, *, flags: str = None):
        """Enable all antiraid modules."""
        recommended = False
        if flags and "--recommended" in flags.lower():
            recommended = True

        if recommended:
            await self._store_module(ctx.guild.id, "massjoin",
                enabled=True, threshold=5, action="ban", lock_channels=True, punish_new=True)
            await self._store_module(ctx.guild.id, "avatar",
                enabled=True, threshold=None, action="kick")
            await self._store_module(ctx.guild.id, "newaccounts",
                enabled=True, threshold=7, action="ban")
            await ctx.success(
                "**Antiraid** is now fully enabled with **recommended settings**.\n"
                "Massjoin: ban @ 5/s, lock, punish | Avatar: kick | New accounts: ban < 7 days"
            )
            return

        current = await self._cached_config(ctx.guild.id)
        if not current.massjoin.enabled:
            await self._store_module(ctx.guild.id, "massjoin",
                enabled=True,
                threshold=current.massjoin.threshold or 5,
                action=current.massjoin.action or "ban",
                lock_channels=current.massjoin.lock_channels,
                punish_new=current.massjoin.punish_new)
        if not current.avatar.enabled:
            await self._store_module(ctx.guild.id, "avatar",
                enabled=True, action=current.avatar.action or "kick")
        if not current.newaccounts.enabled:
            await self._store_module(ctx.guild.id, "newaccounts",
                enabled=True,
                threshold=current.newaccounts.threshold or 7,
                action=current.newaccounts.action or "ban")
        await ctx.success("All **antiraid modules** are now **enabled**.")

    @antiraid.command(
        name="disable",
        usage="",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_disable(self, ctx):
        """Disable all antiraid modules."""
        await self._store_module(ctx.guild.id, "massjoin", enabled=False)
        await self._store_module(ctx.guild.id, "avatar", enabled=False)
        await self._store_module(ctx.guild.id, "newaccounts", enabled=False)
        await ctx.success("All **antiraid modules** are now **disabled**.")

    @antiraid.command(
        name="reset",
        usage="",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_reset(self, ctx):
        """Reset all antiraid configuration for this server."""
        await self.bot.db.execute(
            "DELETE FROM antiraid_config WHERE guild_id = $1",
            ctx.guild.id,
        )
        await self.bot.db.execute(
            "DELETE FROM antiraid_modules WHERE guild_id = $1",
            ctx.guild.id,
        )
        await self.bot.db.execute(
            "DELETE FROM antiraid_whitelist WHERE guild_id = $1",
            ctx.guild.id,
        )
        await self.bot.db.execute(
            "DELETE FROM antiraid_locked_channels WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.success("Antiraid configuration has been **reset**.")


async def setup(bot) -> None:
    await bot.add_cog(Antiraid(bot))
