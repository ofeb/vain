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
from .settings import Settings

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
        channel = settings.channel.mention if settings.channel else "no channel"
        embed.description = "\n".join(
            [
                f"Currently giving out {roles}",
                f"Notifications will be sent in {channel}",
            ]
        )
        if settings.template:
            embed.add_field(name="Script template", value=f"```yaml\n{settings.template}\n```")
        await ctx.reply(embed=embed)

    @vanity.command(name="role", aliases=["roles", "r"])
    @has_permissions(manage_roles=True)
    async def vanity_role(self, ctx: commands.Context, *, role: RoleConvert) -> None:
        """Add or remove a role granted to members who advertise the vanity URL."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        role = role  # type: ignore[assignment]
        settings = await Settings.fetch(self.bot, ctx.guild)
        ids = list(settings.role_ids)
        if role.id in ids:
            view = ConfirmView(ctx)
            ok = await view.prompt(
                f"{role.mention} is already a vanity role. Remove it?"
            )
            if not ok:
                return
            ids = [i for i in ids if i != role.id]
            await settings.upsert(role_ids=ids)
            await ctx.success(f"No longer granting {role.mention} for vanity")
            return

        ids.append(role.id)
        await settings.upsert(role_ids=ids)
        await ctx.success(f"Now granting {role.mention} to members repping the vanity")

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

    @vanity.group(name="message", aliases=["template", "msg", "script"], invoke_without_command=True)
    @has_permissions(manage_messages=True)
    async def vanity_message(self, ctx: commands.Context, *, script: str = None) -> None:
        """Set a custom message template for vanity notifications."""
        assert ctx.guild is not None
        if not await vanity_check(ctx):
            return
        if not script:
            await ctx.send_help(ctx.command)
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(template=script)
        await ctx.success("Updated vanity notification template")

    @vanity_message.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_messages=True)
    async def vanity_message_remove(self, ctx: commands.Context) -> None:
        """Reset the vanity notification message to the default."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.template:
            await ctx.warn("No custom message has been set")
            return
        await settings.upsert(template=None)
        await ctx.success("Custom vanity message reset to default")

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
        await settings.upsert(role_ids=[], channel_id=None, template=None)
        await ctx.success("No longer awarding members for advertising vanity")



Vanity = VanityCommands

__all__ = ["VanityCommands", "Vanity"]
