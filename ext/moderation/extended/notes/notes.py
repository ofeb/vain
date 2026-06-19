from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Notes(Package):
    """notes management"""

    @group(
        name="notes",
        description="View notes on a member",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def notes(self, ctx, member):
        """view notes for member"""
        pass

    @notes.command(
        name="remove",
        description="Removes a note for a member",
    )
    @has_permissions(manage_messages=True)
    async def notes_remove(self, ctx, member, id):
        """remove note for member"""
        pass

    @notes.command(
        name="add",
        description="Add a note for a member",
    )
    @has_permissions(manage_messages=True)
    async def notes_add(self, ctx, member, *, note):
        """add note for member"""
        pass

    @notes.command(
        name="clear",
        description="Clears all notes for a member",
    )
    @has_permissions(manage_messages=True)
    async def notes_clear(self, ctx, member):
        """clear notes for member"""
        pass
