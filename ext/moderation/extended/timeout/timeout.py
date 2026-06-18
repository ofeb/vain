from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class Timeout(Package):
    """timeout management"""

    @group(
        name="timeout",
        description="Mutes the provided member using Discords timeout feature",
        invoke_without_command=True,
    )
    async def timeout(self, ctx, member, duration, *, reason):
        """timeout a member"""
        pass

    @timeout.command(
        name="list",
        description="View list of timed out members",
    )
    @has_permissions(moderate_members=True)
    async def timeout_list(self, ctx):
        """list timed out members"""
        pass
