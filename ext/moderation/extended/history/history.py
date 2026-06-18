from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class History(Package):
    """history management"""

    @group(
        name="history",
        description="View a list of every punishment recorded",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def history(self, ctx, member, command):
        """view history"""
        pass

    @history.command(
        name="view",
        description="View an ID's case log",
    )
    @has_permissions(manage_messages=True)
    async def history_view(self, ctx, case_id):
        """view case log"""
        pass

    @history.command(
        name="remove",
        description="Remove a punishment from a member",
    )
    async def history_remove(self, ctx, member, case_id):
        """remove punishment"""
        pass

    @history.command(
        name="removeall",
        description="Remove all punishments from a member",
    )
    @has_permissions(administrator=True)
    async def history_removeall(self, ctx, member):
        """remove all punishments"""
        pass
