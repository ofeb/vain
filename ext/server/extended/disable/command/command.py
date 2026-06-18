from typing import Union
from discord.ext.commands import group, has_permissions, CommandError, CommandConverter
from discord import Embed, TextChannel, Member
from core.discord.package import Package


class CommandDisableCommands(Package):
    """disable commands per channel"""

    @group(
        name="disablecommand",
        description="Disable a command in a channel",
        invoke_without_command=True,
        example=",disablecommand @jon ping",
    )
    @has_permissions(manage_channels=True)
    async def disablecommand(
        self,
        ctx,
        target: Union[TextChannel, Member],
        *,
        command: CommandConverter,
    ):
        """block a command"""
        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            command.qualified_name,
        )
        if existing:
            if target.id in existing.object_ids:
                raise CommandError(
                    f"{target.mention} already cant use `{command.qualified_name}`"
                )
            ids = list(existing.object_ids)
            kinds = list(existing.object_types)
            ids.append(target.id)
            kinds.append("channel" if isinstance(target, TextChannel) else "member")
            await self.db.execute(
                """UPDATE disabled_commands SET object_ids = $1, object_types = $2 WHERE guild_id = $3 AND command = $4""",
                ids, kinds, ctx.guild.id, command.qualified_name,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_commands (guild_id, command, object_ids, object_types) VALUES($1, $2, $3, $4)""",
                ctx.guild.id,
                command.qualified_name,
                [target.id],
                ["channel" if isinstance(target, TextChannel) else "member"],
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, command.qualified_name)
        return await ctx.success(
            f"**disabled** `{command.qualified_name}` for {target.mention}"
        )

    @disablecommand.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of disabled commands in guild",
    )
    @has_permissions(manage_channels=True)
    async def disablecommand_list(self, ctx):
        """list disabled commands"""
        data = await self.db.fetch(
            """SELECT object_ids, object_types, command FROM disabled_commands WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no commands have been disabled")

        def resolve(obj_id: int):
            if m := ctx.guild.get_member(obj_id):
                return m
            if ch := ctx.guild.get_channel(obj_id):
                return ch
            return None

        lines = []
        for row in data:
            for oid in row.object_ids:
                obj = resolve(oid)
                if obj:
                    lines.append(f"**{row.command}** — {obj.mention}")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Disabled Commands").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @disablecommand.command(name="all", description="Disable a command in every channel")
    @has_permissions(manage_channels=True)
    async def disablecommand_all(self, ctx, *, command: CommandConverter):
        """block command everywhere"""
        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            command.qualified_name,
        )
        if existing:
            ids = list(existing.object_ids)
            kinds = list(existing.object_types)
            fresh = [c.id for c in ctx.guild.text_channels if c.id not in ids]
            ids.extend(fresh)
            kinds.extend(["channel"] * len(fresh))
            await self.db.execute(
                """UPDATE disabled_commands SET object_ids = $1, object_types = $2 WHERE guild_id = $3 AND command = $4""",
                ids, kinds, ctx.guild.id, command.qualified_name,
            )
        else:
            all_ids = [c.id for c in ctx.guild.text_channels]
            await self.db.execute(
                """INSERT INTO disabled_commands (guild_id, command, object_ids, object_types) VALUES($1, $2, $3, $4)""",
                ctx.guild.id,
                command.qualified_name,
                all_ids,
                ["channel"] * len(all_ids),
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, command.qualified_name)
        return await ctx.success(f"**disabled** `{command.qualified_name}` in all channels")
