from __future__ import annotations

import contextlib
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

import discord
from discord import Embed
from discord.ext import commands
from discord.ext.commands import CommandError, FlagConverter, flag, group

from core.discord.package import Package
from core.tools.moderation_logs import build_security_log_embed

from .events import AntiraidEvents
from core.tools.convert import MemberConvert, StatusConvert
from core.tools.flags import AntiRaidFlags

from .models import AntiraidConfig, ModuleConfig

if TYPE_CHECKING:
    from core.vain import Vain

from core.managers.permissions import has_permissions
MASSJOIN_WINDOW = 10


class Antiraid(AntiraidEvents, Package):
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
        guild = self.bot.get_guild(guild_id)
        if guild:
            await self._send_antiraid_log(
                guild,
                build_security_log_embed(
                    color=self.color,
                    title="Raid Mode Updated",
                    lines=[
                        f"**Status** : {'**active**' if active else '**inactive**'}",
                        "> -# Massjoin protection " + ("engaged" if active else "cleared"),
                    ],
                ),
            )
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
            return f"{self._indicator(False)} (do: N/A, threshold: N/A)"

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

    async def _send_antiraid_log(self, guild: discord.Guild, embed: Embed) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        channel_id = await self.db.get_antiraid_log_channel(guild.id)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

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
        else:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await member.kick(reason=reason)

        await self._send_antiraid_log(
            member.guild,
            build_security_log_embed(
                color=self.color,
                title="Antiraid Action",
                lines=[
                    f"**Target** : {member.mention} (`{member.id}`)",
                    f"**Action** : {action}",
                    f"**Reason** : {reason}",
                ],
                footer="Automated antiraid response",
            ),
        )

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
        embed = Embed(
            color=self.color,
            title="Antiraid settings",
            description=(
                f"**Current Raid State:** {'Active' if cfg.raid_active else 'Safe'}"
                "\n\n**Modules**\n"
                f"**Punish New Accounts:** {self._describe('newaccounts', cfg.newaccounts)}\n"
                f"**Mass Bot Raids:** {self._describe('massjoin', cfg.massjoin)}\n"
                f"**Punish Default PFPs:** {self._describe('avatar', cfg.avatar)}"
            ),
        )
        embed.set_author(
            name=str(ctx.author),
            icon_url=ctx.author.display_avatar.url,
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
            return await ctx.success(f"{member} is now temporarily whitelisted and can join")
        return await ctx.success(f"{member} is no longer whitelisted")

    @antiraid_whitelist.command(name="view", aliases=["list"])
    @has_permissions(manage_guild=True)
    async def antiraid_whitelist_view(self, ctx):
        """View all current one-time antiraid whitelist entries."""
        rows = await self.db.fetch_antiraid_whitelist(ctx.guild.id)
        if not rows:
            return await ctx.warn("No **antiraid whitelist** entries exist")

        width = max(2, len(str(len(rows))))
        lines = [
            f"{index:0{width}d} <@{row.user_id}> (`{row.user_id}`)"
            for index, row in enumerate(rows, start=1)
        ]
        return await ctx.paginate(
            Embed(title="Antiraid whitelist", color=self.color).set_author(
                name=str(ctx.author),
                icon_url=ctx.author.display_avatar.url,
            ),
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
            f"{verb} **massjoin** antiraid. "
            f"Punishment set to {action}, "
            f"threshold set to {threshold}, "
            f"lock channels set to {lock_channels}, "
            f"punish new members set to {punish_new}"
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
            f"{verb} **avatar** antiraid. Punishment set to {action}"
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
            f"{verb} **newaccounts** antiraid. "
            f"Punishment set to {action}, threshold set to {threshold}"
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
        """Disable all antiraid modules without deleting configuration."""
        await self._store_module(ctx.guild.id, "massjoin", enabled=False)
        await self._store_module(ctx.guild.id, "avatar", enabled=False)
        await self._store_module(ctx.guild.id, "newaccounts", enabled=False)
        await ctx.success(
            "All **antiraid modules** are now **disabled** - configuration kept. "
            f"Use `{ctx.clean_prefix}antiraid reset` to delete everything."
        )

    @antiraid.command(
        name="reset",
        usage="",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_reset(self, ctx):
        """Reset all antiraid configuration for this server. This cannot be undone."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** antiraid configuration for this server? "
            "This action **cannot be undone**."
        )
        if not ok:
            return await ctx.warn("Antiraid reset **cancelled**")

        unlocked = await self._enable_chat(ctx.guild)
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
        self.config.pop(ctx.guild.id, None)
        self.join_log.pop(ctx.guild.id, None)
        suffix = ""
        if unlocked:
            suffix = f" and **{unlocked}** channel{'s' if unlocked != 1 else ''} unlocked"
        await ctx.success(
            f"Antiraid configuration has been **reset**{suffix}. "
            "This action cannot be undone."
        )
async def setup(bot: Vain) -> None:
    await bot.add_cog(Antiraid(bot))
