"""Guild tag cog - reward members repping the server tag (primary_guild).

See Discord user primary_guild: https://docs.discord.com/developers/resources/user
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import Embed, TextChannel, Thread
from discord.ext import commands
from discord.ext.commands import group, has_permissions

from core.discord.package import Package
from core.discord.views.confirm import ConfirmView
from core.tools.convert.role import RoleConvert

from .events import TagEvents
from .settings import Settings, member_repping_tag, tag_label

if TYPE_CHECKING:
    from core.vain import Vain


class TagCommands(TagEvents, Package):
    """Manage rewards for members displaying this server's tag."""

    @group(
        name="tag",
        aliases=["servertag", "gtag"],
        invoke_without_command=True,
        description="Manage server tag role rewards",
    )
    @has_permissions(manage_roles=True)
    async def tag(self, ctx: commands.Context) -> None:
        """Like vanity, but for Discord server tags (primary guild identity)."""
        await ctx.send_help(ctx.command)

    @tag.command(name="settings", aliases=["config", "cfg"])
    @has_permissions(manage_guild=True)
    async def tag_settings(self, ctx: commands.Context) -> None:
        """View guild tag reward configuration."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        embed = Embed(title="Server Tag Rewards", color=self.color)
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        roles = ", ".join(r.mention for r in settings.roles) or "no roles"
        unassignable = [
            r.mention for r in settings.roles if r not in settings.assignable_roles
        ]
        channel = settings.channel.mention if settings.channel else "no channel"
        lines = [
            f"Roles: {roles}",
            f"Notifications: {channel}",
            "> -# Awards members whose **primary guild** tag is this server.",
        ]
        if unassignable:
            lines.append(
                f"> -# cannot assign (hierarchy): {', '.join(unassignable)}"
            )
        embed.description = "\n".join(lines)
        template = settings.template or settings._default_template
        embed.add_field(
            name="Script" + (" (default)" if not settings.template else ""),
            value=f"```yaml\n{template}\n```",
        )
        await ctx.reply(embed=embed)

    @tag.command(name="role", aliases=["roles", "r"])
    @has_permissions(manage_roles=True)
    async def tag_role(self, ctx: commands.Context, *, role: RoleConvert) -> None:
        """Set the tag reward role."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        old_ids = list(settings.role_ids)
        await settings.upsert(role_ids=[role.id])
        if old_ids and old_ids != [role.id]:
            old_mentions = ", ".join(
                (ctx.guild.get_role(i).mention if ctx.guild.get_role(i) else f"`{i}`")
                for i in old_ids
            )
            msg = f"Tag role set to {role.mention} (replaced {old_mentions})"
        else:
            msg = f"Tag role set to {role.mention}"
        if not role.is_assignable():
            await ctx.warn(
                f"{msg}\n> -# I **cannot assign** it - move my role **above** "
                f"{role.mention} in Server Settings → Roles."
            )
        else:
            await ctx.success(msg)
        try:
            await self.sync_guild(ctx.guild, notify=False)
        except Exception:
            pass

    @tag.group(name="channel", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def tag_channel(
        self,
        ctx: commands.Context,
        *,
        channel: TextChannel | Thread = None,
    ) -> None:
        """Set the channel for tag notifications."""
        assert ctx.guild is not None
        if channel is None:
            await ctx.send_help(ctx.command)
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        if settings.channel_id == channel.id:
            await ctx.warn(f"{channel.mention} is already the notification channel")
            return
        await settings.upsert(channel_id=channel.id)
        await ctx.success(f"Tag notifications will be sent to {channel.mention}")

    @tag_channel.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_channels=True)
    async def tag_channel_remove(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.channel:
            await ctx.warn("No notification channel has been set")
            return
        await settings.upsert(channel_id=None)
        await ctx.success("No longer sending tag notifications")

    @tag.group(
        name="script",
        aliases=["message", "template", "msg"],
        invoke_without_command=True,
        usage="[template]",
        example=",tag script thank you {user.mention} for repping {tag}",
        description="Set a custom notification template",
    )
    @has_permissions(manage_messages=True)
    async def tag_script(self, ctx: commands.Context, *, template: str = None) -> None:
        """Set a custom notification template. Supports `{user.mention}` and `{tag}`."""
        assert ctx.guild is not None
        if not template:
            await ctx.send_help(ctx.command)
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(template=template)
        await ctx.success("Updated tag notification template")

    @tag_script.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_messages=True)
    async def tag_script_remove(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.template:
            await ctx.warn("No custom message has been set")
            return
        await settings.upsert(template=None)
        await ctx.success("Tag message reset to default")

    @tag.command(name="check", aliases=["me", "status", "test"])
    async def tag_check(self, ctx: commands.Context, member: discord.Member = None) -> None:
        """Check whether a member is repping this server's tag and force-sync."""
        assert ctx.guild is not None
        member = member or ctx.author
        settings = await Settings.fetch(self.bot, ctx.guild)
        on = member_repping_tag(member, ctx.guild)
        tag = tag_label(member)
        await self.sync_member(member, notify=bool(on and settings.channel_id))
        has_roles = any(r in member.roles for r in settings.assignable_roles)
        lines = [
            f"**Tag match:** {'yes' if on else 'no'}"
            + (f" · **{tag}**" if tag else ""),
            f"**Roles assignable:** "
            f"{', '.join(r.mention for r in settings.assignable_roles) or 'none'}",
            f"**Has reward role:** {'yes' if has_roles else 'no'}",
            f"**Notify channel:** "
            f"{settings.channel.mention if settings.channel else 'not set'}",
        ]
        if on:
            await ctx.success("\n".join(lines))
        else:
            await ctx.warn(
                "\n".join(lines)
                + "\n> -# Enable this server's **tag** on your profile (primary guild)."
            )

    @tag.command(name="sync", description="Scan members and apply tag roles")
    @has_permissions(manage_roles=True)
    async def tag_sync(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        count = await self.sync_guild(ctx.guild, notify=False)
        await ctx.success(f"Synced tag rewards · **{count}** member(s) matching")

    @tag.command(name="reset", aliases=["clear"])
    @has_permissions(manage_roles=True)
    async def tag_reset(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        view = ConfirmView(ctx)
        if not await view.prompt(
            "Reset **all** server tag settings? This action **cannot be undone**."
        ):
            return await ctx.warn("Tag reset **cancelled**")
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(role_ids=[], channel_id=None, template=None)
        await ctx.success(
            "Cleared server tag rewards. This action cannot be undone."
        )


Tag = TagCommands

__all__ = ["TagCommands", "Tag"]
