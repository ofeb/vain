from typing import Union
from discord.ext.commands import group, has_permissions, CommandError, CommandConverter
from discord import TextChannel, Member
from core.discord.package import Package


class CommandEnableCommands(Package):
    """enable commands per channel"""

    @group(
        name="enablecommand",
        description="Enable a previously disabled command in a channel",
        invoke_without_command=True,
        example=",enablecommand @jon ping",
    )
    @has_permissions(manage_channels=True)
    async def enablecommand(
        self,
        ctx,
        target: Union[TextChannel, Member],
        *,
        command: CommandConverter,
    ):
        """enable a command"""
        record = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            command.qualified_name,
        )
        if not record:
            raise CommandError(f"`{command.qualified_name}` wasnt disabled anywhere")
        try:
            idx = record.object_ids.index(target.id)
        except ValueError:
            raise CommandError(f"{target.mention} doesnt have that command disabled")
        obj_ids = list(record.object_ids)
        obj_types = list(record.object_types)
        obj_ids.pop(idx)
        obj_types.pop(idx)
        await self.db.execute(
            """UPDATE disabled_commands SET object_ids = $1, object_types = $2 WHERE guild_id = $3 AND command = $4""",
            obj_ids, obj_types, ctx.guild.id, command.qualified_name,
        )
        return await ctx.success(
            f"**enabled** `{command.qualified_name}` for {target.mention}"
        )

    @enablecommand.command(name="all", description="Enable a command in every channel")
    @has_permissions(manage_channels=True)
    async def enablecommand_all(self, ctx, *, command: CommandConverter):
        """enable command everywhere"""
        record = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            command.qualified_name,
        )
        if not record:
            raise CommandError(f"`{command.qualified_name}` wasnt disabled anywhere")
        obj_ids = list(record.object_ids)
        obj_types = list(record.object_types)
        for ch in ctx.guild.channels:
            try:
                idx = obj_ids.index(ch.id)
                obj_ids.pop(idx)
                obj_types.pop(idx)
            except (ValueError, Exception):
                pass
        await self.db.execute(
            """UPDATE disabled_commands SET object_ids = $1, object_types = $2 WHERE guild_id = $3 AND command = $4""",
            obj_ids, obj_types, ctx.guild.id, command.qualified_name,
        )
        return await ctx.success(
            f"**enabled** `{command.qualified_name}` in all channels"
        )
