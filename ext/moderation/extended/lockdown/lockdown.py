from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Lockdown(Package):
    """lockdown management"""

    @group(
        name="lockdown",
        description="Lockdown a channel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def lockdown(self, ctx, channel, *, reason):
        """lockdown a channel"""
        pass

    @lockdown.command(
        name="all",
        description="Locks all channels",
    )
    @has_permissions(manage_channels=True)
    async def lockdown_all(self, ctx, *, reason):
        """lockdown all channels"""
        pass

    @lockdown.command(
        name="role",
        description="No description given",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_role(self, ctx, role):
        """lockdown role"""
        pass

    @lockdown.command(
        name="ignore",
        description="Blocks a channel from being altered when using the 'unlock all' command",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore(self, ctx):
        """ignore channel from lockdown"""
        pass

    @lockdown.command(
        name="ignore remove",
        description="Remove an ignored lockdown channel",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore_remove(self, ctx, channel):
        """remove ignored lockdown channel"""
        pass

    @lockdown.command(
        name="ignore list",
        description="View all ignored lockdown channels",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore_list(self, ctx):
        """list ignored lockdown channels"""
        pass

    @lockdown.command(
        name="ignore add",
        description="Set an ignored lockdown channel",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore_add(self, ctx, channel):
        """add ignored lockdown channel"""
        pass
