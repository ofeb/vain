from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class Slowmode(Package):
    """slowmode management"""

    @group(
        name="slowmode",
        description="Restricts members to sending one message per interval",
        invoke_without_command=True,
    )
    async def slowmode(self, ctx):
        """slowmode group help"""
        return await ctx.send_help(ctx.command)

    @slowmode.command(
        name="off",
        description="Disables slowmode in a channel",
    )
    @has_permissions(manage_channels=True)
    async def slowmode_off(self, ctx, channel):
        """disable slowmode"""
        pass

    @slowmode.command(
        name="on",
        description="Enable slowmode in a channel",
    )
    @has_permissions(manage_channels=True)
    async def slowmode_on(self, ctx, channel, delay_time):
        """enable slowmode"""
        pass
