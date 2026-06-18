from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class Role(Package):
    """role management"""

    @group(
        name="role",
        description="Modify a member's roles",
        invoke_without_command=True,
    )
    async def role(self, ctx, member, role):
        """modify member roles"""
        pass

    @role.command(
        name="has",
        description="Add a role to members with a specific role",
    )
    async def role_has(self, ctx, role, assign_role):
        """add role to members with role"""
        pass

    @role.command(
        name="has remove",
        description="Remove a role from members with a specific role",
    )
    async def role_has_remove(self, ctx, role, remove_role):
        """remove role from members with role"""
        pass

    @role.command(
        name="remove",
        description="Removes role from a member",
    )
    async def role_remove(self, ctx, member, role):
        """remove role from member"""
        pass

    @role.command(
        name="hoist",
        description="Toggle hoisting a role",
    )
    async def role_hoist(self, ctx, role):
        """toggle role hoist"""
        pass

    @role.command(
        name="humans",
        description="Add a role to all humans",
    )
    async def role_humans(self, ctx, role, flags):
        """add role to all humans"""
        pass

    @role.command(
        name="humans remove",
        description="Remove a role from all humans",
    )
    async def role_humans_remove(self, ctx, role):
        """remove role from all humans"""
        pass

    @role.command(
        name="add",
        description="Adds role to a member",
    )
    async def role_add(self, ctx, member, role):
        """add role to member"""
        pass

    @role.command(
        name="color",
        description="Set a color for a role",
    )
    async def role_color(self, ctx, colour, role):
        """set role color"""
        pass

    @role.command(
        name="color gradient",
        description="Set a gradient color for a role",
    )
    async def role_color_gradient(self, ctx, colour, second_colour, role):
        """set role gradient color"""
        pass

    @role.command(
        name="delete",
        description="Deletes a role",
    )
    async def role_delete(self, ctx, role):
        """delete role"""
        pass

    @role.command(
        name="mentionable",
        description="Toggle mentioning a role",
    )
    async def role_mentionable(self, ctx, role):
        """toggle role mentionable"""
        pass

    @role.command(
        name="cancel",
        description="Cancels a mass role task running",
    )
    async def role_cancel(self, ctx):
        """cancel mass role task"""
        pass

    @role.command(
        name="restore",
        description="Restore roles to a member",
    )
    async def role_restore(self, ctx, member):
        """restore member roles"""
        pass

    @role.command(
        name="icon",
        description="Set an icon for a role",
    )
    async def role_icon(self, ctx, url, role):
        """set role icon"""
        pass

    @role.command(
        name="topcolor",
        description="Changes your highest roles color",
    )
    async def role_topcolor(self, ctx, colour, member):
        """change highest role color"""
        pass

    @role.command(
        name="bots",
        description="Add a role to all bots",
    )
    async def role_bots(self, ctx, role):
        """add role to all bots"""
        pass

    @role.command(
        name="bots remove",
        description="Remove a role from all bots",
    )
    async def role_bots_remove(self, ctx, role):
        """remove role from all bots"""
        pass

    @role.command(
        name="edit",
        description="Change a role name",
    )
    async def role_edit(self, ctx, role, *, name):
        """edit role name"""
        pass

    @role.command(
        name="create",
        description="Creates a role with optional color",
    )
    async def role_create(self, ctx, color, role):
        """create role"""
        pass
