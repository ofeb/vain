"""Guild tag cog — reward members repping the server tag (primary_guild).

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
        description="Manage server tag (primary guild) role rewards",
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
        channel = settings.channel.mention if settings.channel else "no channel"
        embed.description = "\n".join(
            [
                f"Roles: {roles}",
                f"Notifications: {channel}",
                "-# Awards members whose **primary guild** tag is this server.",
            ]
        )
        if settings.template:
            embed.add_field(name="Template", value=f"```yaml\n{settings.template}\n```")
        await ctx.reply(embed=embed)

    @tag.command(name="role", aliases=["roles", "r"])
    @has_permissions(manage_roles=True)
    async def tag_role(self, ctx: commands.Context, *, role: RoleConvert) -> None:
        """Toggle a role for members displaying this server's tag."""
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        ids = list(settings.role_ids)
        if role.id in ids:
            view = ConfirmView(ctx)
            if not await view.prompt(f"Remove {role.mention} from tag roles?"):
                return
            ids = [i for i in ids if i != role.id]
            await settings.upsert(role_ids=ids)
            await ctx.success(f"No longer granting {role.mention} for the server tag")
            return
        ids.append(role.id)
        await settings.upsert(role_ids=ids)
        await ctx.success(f"Now granting {role.mention} to members repping the server tag")

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

    @tag.group(name="message", aliases=["template", "msg", "script"], invoke_without_command=True)
    @has_permissions(manage_messages=True)
    async def tag_message(self, ctx: commands.Context, *, script: str = None) -> None:
        """Set a custom notification template. Supports `{user.mention}` and `{tag}`."""
        assert ctx.guild is not None
        if not script:
            await ctx.send_help(ctx.command)
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(template=script)
        await ctx.success("Updated tag notification template")

    @tag_message.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_messages=True)
    async def tag_message_remove(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.template:
            await ctx.warn("No custom message has been set")
            return
        await settings.upsert(template=None)
        await ctx.success("Tag message reset to default")

    @tag.command(name="check", aliases=["me", "status"])
    async def tag_check(self, ctx: commands.Context, member: discord.Member = None) -> None:
        """Check whether a member is repping this server's tag."""
        assert ctx.guild is not None
        member = member or ctx.author
        on = member_repping_tag(member, ctx.guild)
        tag = tag_label(member)
        if on:
            await ctx.success(
                f"{member.mention} is repping this server"
                + (f" with tag **{tag}**" if tag else "")
            )
        else:
            await ctx.warn(
                f"{member.mention} is **not** displaying this server's tag as their primary guild."
            )

    @tag.command(name="reset", aliases=["clear"])
    @has_permissions(manage_roles=True)
    async def tag_reset(self, ctx: commands.Context) -> None:
        assert ctx.guild is not None
        view = ConfirmView(ctx)
        if not await view.prompt("Reset **all** server tag settings?"):
            return
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(role_ids=[], channel_id=None, template=None)
        await ctx.success("Cleared server tag rewards")


Tag = TagCommands

__all__ = ["TagCommands", "Tag"]
