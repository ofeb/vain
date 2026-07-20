from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Stickyrole(Package):
    """stickyrole management"""

    @group(
        name="stickyrole",
        description="Reapplies a role on join",
        invoke_without_command=True,
    )
    @has_permissions(server_owner=True)
    async def stickyrole(self, ctx, member, role):
        """set sticky role for member"""
        pass

    @stickyrole.command(
        name="list",
        description="View a list of every sticky role",
    )
    @has_permissions(server_owner=True)
    async def stickyrole_list(self, ctx):
        """list sticky roles"""
        pass

    @stickyrole.command(
        name="add",
        description="Reapplies a role on join",
    )
    @has_permissions(server_owner=True)
    async def stickyrole_add(self, ctx, member, role):
        """add sticky role"""
        pass

    @stickyrole.command(
        name="remove",
        description="Removes sticky role on join",
    )
    @has_permissions(server_owner=True)
    async def stickyrole_remove(self, ctx, member, role):
        """remove sticky role"""
        pass
