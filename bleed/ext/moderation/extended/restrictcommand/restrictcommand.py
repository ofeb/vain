from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class Restrictcommand(Package):
    """restrictcommand management"""

    @group(
        name="restrictcommand",
        description="Only allows people with a certain role to use command",
        invoke_without_command=True,
    )
    async def restrictcommand(self, ctx, cmd, role):
        """restrict command to role"""
        pass

    @restrictcommand.command(
        name="list",
        description="View a list of every restricted command",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_list(self, ctx, role_or_command):
        """list restricted commands"""
        pass

    @restrictcommand.command(
        name="remove",
        description="Removes the specified roles exclusive permission to use a command",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_remove(self, ctx, cmd, role):
        """remove command restriction"""
        pass

    @restrictcommand.command(
        name="reset",
        description="Removes every restricted command",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_reset(self, ctx):
        """reset all command restrictions"""
        pass

    @restrictcommand.command(
        name="add",
        description="Allows the specified role exclusive permission to use a command",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_add(self, ctx, cmd, role):
        """add command restriction"""
        pass
