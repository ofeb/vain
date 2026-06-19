from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Revokefiles(Package):
    """revokefiles management"""

    @group(
        name="revokefiles",
        description="Removes/assigns the permission to attach files & embed links in the current channel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def revokefiles(self, ctx):
        """revokefiles group help"""
        return await ctx.send_help(ctx.command)

    @revokefiles.command(
        name="on",
        description="Enable permissions to attach files & embed links in a channel",
    )
    @has_permissions(manage_channels=True)
    async def revokefiles_on(self, ctx, channel):
        """enable file permissions"""
        pass

    @revokefiles.command(
        name="off",
        description="Disables permissions to attach files & embed links in a channel",
    )
    @has_permissions(manage_channels=True)
    async def revokefiles_off(self, ctx, channel):
        """disable file permissions"""
        pass
