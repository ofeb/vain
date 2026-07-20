"""Vanity role cog — reward members who put the guild vanity in their status."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord
from discord import Embed, Role, TextChannel, Thread
from discord.ext import commands
from discord.ext.commands import group, has_permissions

from core.discord.package import Package
from core.discord.views.confirm import ConfirmView
from core.tools.convert.role import RoleConvert
from core.tools.embed import Script

from .events import VanityEvents
from .settings import Settings, get_status, member_repping_vanity

if TYPE_CHECKING:
    from core.vain import Vain


async def vanity_check(ctx: commands.Context) -> bool:
    if not (ctx.guild and ctx.guild.vanity_url_code):
        await ctx.warn(f"**{ctx.guild.name if ctx.guild else 'This server'}** has no vanity URL set.")
        return False
    return True


class VanityCommands(VanityEvents, Package):
    """Manage vanity role assignments for your guild."""

    @group(
        name="vanity",
        aliases=["vr"],
        invoke_without_command=True,
        description="Manage vanity role rewards for status repping",
    )
    @has_permissions(manage_roles=True)
    async def vanity(self, ctx: commands.Context) -> None:
        """Manage vanity role assignments. Notifications fire when a member sets their status to your vanity URL."""
        if not await vanity_check(ctx):
            return
        await ctx.send_help(ctx.command)

    @vanity.command(name="settings", aliases=["config", "cfg"])
    @has_permissions(manage_guild=True)
    async def vanity_settings(self, ctx: commands.Context) -> None:
        """View the current vanity role configuration."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.role_ids and not settings.channel_id and not settings.template:
            await ctx.warn(
                f"**{ctx.me.display_name}** doesn't dispatch vanity notifications yet."
            )
            return

        embed = Embed(
            title=f"/{ctx.guild.vanity_url_code}",
            color=self.color,
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        roles = ", ".join(r.mention for r in settings.roles) or "no roles"
        unassignable = [
            r.mention for r in settings.roles if r not in settings.assignable_roles
        ]
        channel = settings.channel.mention if settings.channel else "no channel"
        lines = [
            f"Currently giving out {roles}",
            f"Notifications will be sent in {channel}",
            f"Match mode: **{'strict' if settings.strict else 'not strict'}**",
        ]
        if unassignable:
            lines.append(
                f"-# cannot assign (hierarchy): {', '.join(unassignable)}"
            )
        embed.description = "\n".join(lines)
        template = settings.template or settings._default_template
        embed.add_field(
            name="Script" + (" (default)" if not settings.template else ""),
            value=f"```yaml\n{template}\n```",
        )
        await ctx.reply(embed=embed)

    @vanity.command(name="role", aliases=["roles", "r"])
    @has_permissions(manage_roles=True)
    async def vanity_role(self, ctx: commands.Context, *, role: RoleConvert) -> None:
        """Set the vanity reward role."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        old_ids = list(settings.role_ids)
        
        await settings.upsert(role_ids=[role.id])
        if old_ids and old_ids != [role.id]:
            old_mentions = ", ".join(
                (ctx.guild.get_role(i).mention if ctx.guild.get_role(i) else f"`{i}`")
                for i in old_ids
            )
            msg = f"Vanity role set to {role.mention} (replaced {old_mentions})"
        else:
            msg = f"Vanity role set to {role.mention}"
        if not role.is_assignable():
            await ctx.warn(
                f"{msg}\n-# I **cannot assign** it — move my role **above** "
                f"{role.mention} in Server Settings → Roles."
            )
        else:
            await ctx.success(msg)
        try:
            await self.sync_guild(ctx.guild, notify=False)
        except Exception:
            pass

    @vanity.group(name="channel", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def vanity_channel(
        self,
        ctx: commands.Context,
        *,
        channel: TextChannel | Thread = None,
    ) -> None:
        """Set the channel for vanity notifications."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        if channel is None:
            await ctx.send_help(ctx.command)
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        if settings.channel_id == channel.id:
            await ctx.warn(f"{channel.mention} is already the notification channel")
            return
        await settings.upsert(channel_id=channel.id)
        await ctx.success(f"Vanity notifications will be sent to {channel.mention}")
        try:
            await self.sync_guild(ctx.guild, notify=False)
        except Exception:
            pass

    @vanity_channel.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_channels=True)
    async def vanity_channel_remove(self, ctx: commands.Context) -> None:
        """Remove the vanity notification channel."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.channel:
            await ctx.warn("No notification channel has been set")
            return
        await settings.upsert(channel_id=None)
        await ctx.success("No longer sending vanity notifications")

    @vanity.group(
        name="script",
        aliases=["message", "template", "msg"],
        invoke_without_command=True,
        usage="[template]",
        example=",vanity script thank you {user.mention} for repping /{guild.vanity}",
        description="Set a custom notification template",
    )
    @has_permissions(manage_messages=True)
    async def vanity_script(self, ctx: commands.Context, *, template: str = None) -> None:
        """Set a custom message template for vanity notifications."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        if not template:
            await ctx.send_help(ctx.command)
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(template=template)
        await ctx.success("Updated vanity notification template")

    @vanity_script.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_messages=True)
    async def vanity_script_remove(self, ctx: commands.Context) -> None:
        """Reset the vanity notification message to the default."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.template:
            await ctx.warn("No custom message has been set")
            return
        await settings.upsert(template=None)
        await ctx.success("Custom vanity message reset to default")

    @vanity.command(
        name="strict",
        usage="<on|off>",
        example=",vr strict off",
        description="Toggle strict vanity matching (default: off)",
    )
    @has_permissions(manage_guild=True)
    async def vanity_strict(self, ctx: commands.Context, state: str = None) -> None:
        """Strict: require /vanity or discord.gg/vanity style match. Off = code anywhere in status."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not state:
            mode = "strict" if settings.strict else "not strict"
            await ctx.success(f"Vanity matching is **{mode}**")
            return
        low = state.lower().strip()
        if low in {"on", "enable", "true", "yes", "1", "strict"}:
            await settings.upsert(strict=True)
            await ctx.success("Vanity matching is now **strict**")
            return
        if low in {"off", "disable", "false", "no", "0", "loose"}:
            await settings.upsert(strict=False)
            await ctx.success("Vanity matching is now **not strict** (default)")
            return
        await ctx.warn("Use `on` or `off`")

    @vanity.command(
        name="check",
        aliases=["me", "status", "test"],
        description="Check if a member is repping vanity and force-sync their roles",
        example=",vr check @user",
    )
    async def vanity_check(
        self, ctx: commands.Context, member: discord.Member = None
    ) -> None:
        """Debug vanity detection and apply roles/message if they're repping now."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        member = member or ctx.author
        settings = await Settings.fetch(self.bot, ctx.guild)
        raw = get_status(member)
        repping = member_repping_vanity(member, ctx.guild, strict=settings.strict)
        code = ctx.guild.vanity_url_code or "?"

        grantable = settings.grantable_roles
        had_roles = any(r in member.roles for r in grantable)

        
        await self.sync_member(
            member,
            notify=bool(repping and settings.channel_id),
        )
        
        try:
            member = ctx.guild.get_member(member.id) or member
        except Exception:
            pass
        has_roles = any(r in member.roles for r in grantable)

        lines = [
            f"**Vanity:** `/{code}`",
            f"**Status text seen:** `{raw or '∅ empty'}`",
            f"**Match ({'strict' if settings.strict else 'loose'}):** "
            f"{'yes' if repping else 'no'}",
            f"**Roles (will try):** "
            f"{', '.join(r.mention for r in grantable) or 'none'}",
            f"**Bot can assign:** "
            f"{', '.join(r.mention for r in settings.assignable_roles) or 'none — move bot role higher'}",
            f"**Member has reward role:** {'yes' if has_roles else 'no'}"
            + ("" if had_roles == has_roles else " *(updated)*"),
            f"**Notify channel:** "
            f"{settings.channel.mention if settings.channel else 'not set'}",
        ]
        if repping:
            await ctx.success("\n".join(lines))
        else:
            await ctx.warn(
                "\n".join(lines)
                + "\n-# Tip: set custom status to `/"
                + code
                + "` then run `,vanity check` again."
            )

    @vanity.command(
        name="sync",
        description="Scan online members and apply vanity roles",
    )
    @has_permissions(manage_roles=True)
    async def vanity_sync(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        count = await self.sync_guild(ctx.guild, notify=False)
        await ctx.success(
            f"Synced vanity · **{count}** member(s) currently matching "
            f"`/{ctx.guild.vanity_url_code}`"
        )

    @vanity.command(name="reset", aliases=["clear"])
    @has_permissions(manage_roles=True)
    async def vanity_reset(self, ctx: commands.Context) -> None:
        """Reset all vanity role settings for this guild."""
        assert ctx.guild is not None
        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** vanity settings? This cannot be undone."
        )
        if not ok:
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(
            role_ids=[], channel_id=None, template=None, strict=False
        )
        await ctx.success("No longer awarding members for advertising vanity")


Vanity = VanityCommands

__all__ = ["VanityCommands", "Vanity"]
