from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Forcenickname(Package):
    """forcenickname management"""

    @group(
        name="forcenickname",
        description="Force a members current nickname",
        invoke_without_command=True,
    )
    async def forcenickname(self, ctx, member, *, name_to_set):
        """force nickname for member"""
        pass

    @forcenickname.command(
        name="list",
        description="View a list of all forced nicknames",
    )
    @has_permissions(manage_guild=True)
    async def forcenickname_list(self, ctx):
        """list forced nicknames"""
        pass
