from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Proof(Package):
    """proof management"""

    @group(
        name="proof",
        description="No description given",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def proof(self, ctx):
        """proof group help"""
        return await ctx.send_help(ctx.command)

    @proof.command(
        name="list",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def proof_list(self, ctx, case_id):
        """list proof for case"""
        pass

    @proof.command(
        name="add",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def proof_add(self, ctx, case_id, media_url):
        """add proof to case"""
        pass

    @proof.command(
        name="view",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def proof_view(self, ctx, case_id):
        """view proof for case"""
        pass

    @proof.command(
        name="set",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def proof_set(self, ctx, case_id, *, explanation):
        """set proof explanation"""
        pass

    @proof.command(
        name="remove",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def proof_remove(self, ctx, case_id, index):
        """remove proof from case"""
        pass
