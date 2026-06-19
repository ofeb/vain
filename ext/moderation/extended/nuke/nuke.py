from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Nuke(Package):
    """nuke management"""

    @group(
        name="nuke",
        description="No description given",
        invoke_without_command=True,
    )
    async def nuke(self, ctx):
        """nuke group help"""
        return await ctx.send_help(ctx.command)

    @nuke.command(
        name="view",
        description="No description given",
    )
    async def nuke_view(self, ctx, channel):
        """view nuke settings"""
        pass

    @nuke.command(
        name="add",
        description="No description given",
    )
    async def nuke_add(self, ctx, channel, interval, *, message):
        """add nuke to channel"""
        pass

    @nuke.command(
        name="remove",
        description="No description given",
    )
    async def nuke_remove(self, ctx, channel):
        """remove nuke from channel"""
        pass

    @nuke.command(
        name="list",
        description="No description given",
    )
    async def nuke_list(self, ctx):
        """list all nukes"""
        pass

    @nuke.command(
        name="archive",
        description="No description given",
    )
    async def nuke_archive(self, ctx, channel, setting):
        """archive nuke settings"""
        pass
