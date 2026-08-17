from discord.ext.commands import group, CommandError
from discord import Embed
from core.discord.package import Package


from core.managers.converters import CommandConverter
from core.managers.permissions import has_permissions
class AliasCommands(Package):
    """command alias management"""

    @group(
        name="alias",
        aliases=["shortcut"],
        description="Create your own shortcuts for commands",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def alias(self, ctx):
        """alias group help"""
        return await ctx.send_help(ctx.command)

    @alias.command(
        name="view",
        aliases=["show"],
        description="View command execution for alias",
        example=",alias view hi",
    )
    @has_permissions(manage_guild=True)
    async def alias_view(self, ctx, *, shortcut: str):
        """view alias target"""
        cmd_name = await self.db.fetchval(
            """SELECT command_name FROM aliases WHERE guild_id = $1 AND alias = $2""",
            ctx.guild.id,
            shortcut,
        )
        if not cmd_name:
            raise CommandError(f"no alias found for `{shortcut[:25]}`")
        cmd = self.bot.get_command(cmd_name)
        return await ctx.normal(
            f"**{shortcut}** runs `{cmd.qualified_name}`", emoji="ℹ️"
        )

    @alias.command(
        name="removeall",
        aliases=["delall", "deleteeall"],
        description="Remove an alias for command",
        example=",alias removeall avatar",
    )
    @has_permissions(manage_guild=True)
    async def alias_removeall(self, ctx, *, command: CommandConverter):
        """remove every alias for command"""
        await self.db.execute(
            """DELETE FROM aliases WHERE command_name = $1 AND guild_id = $2""",
            command.qualified_name,
            ctx.guild.id,
        )
        return await ctx.success(f"Removed aliases for `{command.qualified_name}`")

    @alias.command(
        name="list",
        description="List every alias for all commands",
    )
    @has_permissions(manage_guild=True)
    async def alias_list(self, ctx):
        """list all server aliases"""
        entries = await self.db.fetch(
            """SELECT alias, command_name FROM aliases WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not entries:
            raise CommandError("no aliases have been added")
        lines = [
            f"`{i}` **{e.alias}** runs `{e.command_name}`"
            for i, e in enumerate(entries, start=1)
        ]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Aliases").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            lines,
        )

    @alias.command(
        name="add",
        aliases=["create"],
        description="Create an alias for command",
        example=",alias add hi avatar",
    )
    @has_permissions(manage_guild=True)
    async def alias_add(self, ctx, shortcut: str, *, command: CommandConverter):
        """add a command alias"""
        await self.db.execute(
            """INSERT INTO aliases (guild_id, command_name, alias) VALUES($1, $2, $3) ON CONFLICT(guild_id, alias) DO UPDATE SET command_name = excluded.command_name""",
            ctx.guild.id,
            command.qualified_name,
            shortcut,
        )
        return await ctx.success(f"Alias added\n> -# **{shortcut}** → `{command.qualified_name}`")

    @alias.command(
        name="remove",
        aliases=["del", "delete"],
        description="Remove an alias for command",
        example=",alias remove hi",
    )
    @has_permissions(manage_guild=True)
    async def alias_remove(self, ctx, *, shortcut: str):
        """delete an alias"""
        await self.db.execute(
            """DELETE FROM aliases WHERE guild_id = $1 AND alias = $2""",
            ctx.guild.id,
            shortcut,
        )
        return await ctx.success(f"Removed alias\n> -# **`{shortcut}`**")

    @alias.command(
        name="reset",
        aliases=["clear"],
        description="Reset every alias for all commands. This can't be undone.",
    )
    @has_permissions(manage_guild=True)
    async def alias_reset(self, ctx):
        """wipe all aliases"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** command aliases for this server? "
            "This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **alias reset was cancelled**")
        await self.db.execute(
            """DELETE FROM aliases WHERE guild_id = $1""", ctx.guild.id
        )
        return await ctx.success(
            "All aliases cleared\n> -# **this action can't be undone**"
        )
