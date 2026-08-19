from __future__ import annotations

import discord
from discord.ext.commands import group, CommandError
from discord import TextChannel

from core.discord.package import Package
from core.managers.permissions import has_permissions


class Revokefiles(Package):
    """revokefiles management"""

    async def _set_file_perms(
        self,
        ctx,
        channel: TextChannel,
        *,
        allow: bool,
    ) -> None:
        everyone = ctx.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.attach_files = allow
        overwrite.embed_links = allow
        await channel.set_permissions(
            everyone,
            overwrite=overwrite,
            reason=f"revokefiles {'on' if allow else 'off'} by {ctx.author}",
        )

    @group(
        name="revokefiles",
        aliases=["rf"],
        description="removes/assigns the permission to attach files & embed links in the current channel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def revokefiles(self, ctx):
        """revokefiles group help"""
        return await ctx.send_help(ctx.command)

    @revokefiles.command(
        name="on",
        aliases=["enable", "allow"],
        description="enable permissions to attach files & embed links in a channel",
        example=",revokefiles on",
    )
    @has_permissions(manage_channels=True)
    async def revokefiles_on(self, ctx, channel: TextChannel = None):
        """enable file permissions (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        try:
            await self._set_file_perms(ctx, channel, allow=True)
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to update permissions: {e}")

        return await ctx.success(
            f"Enabled **attach files** & **embed links** in {channel.mention}"
        )

    @revokefiles.command(
        name="off",
        aliases=["disable", "deny"],
        description="disables permissions to attach files & embed links in a channel",
        example=",revokefiles off",
    )
    @has_permissions(manage_channels=True)
    async def revokefiles_off(self, ctx, channel: TextChannel = None):
        """disable file permissions (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        try:
            await self._set_file_perms(ctx, channel, allow=False)
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to update permissions: {e}")

        return await ctx.success(
            f"Disabled **attach files** & **embed links** in {channel.mention}"
        )
