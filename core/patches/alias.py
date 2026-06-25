"""command alias converter and handler.
lets users define custom aliases for commands.
use AliasConverter in command params"""

from typing import List, Optional, Union
from discord.ext.commands import Command, Converter, Context, Group
from discord.ext.commands.errors import CommandError
from fast_string_match import closest_match


class Alias:
    """pairing of an alias string to a command"""
    def __init__(self, command: Union[Command, Group, str], alias: str):
        self.command = command
        self.alias = alias


async def _build_list(ctx: Context) -> dict:
    """build flat command name map on bot"""
    cmds: dict = {}
    for cmd in ctx.bot.walk_commands():
        cmds[cmd.qualified_name.lower()] = cmd
        for a in cmd.aliases:
            prefix = f"{cmd.parent.qualified_name.lower()} " if cmd.parent else ""
            cmds[f"{prefix}{a.lower()}"] = cmd
    ctx.bot.command_list = cmds
    return cmds


class CmdConverter(Converter):
    """convert string to Command with fuzzy fallback"""
    async def convert(self, ctx: Context, arg: str) -> Optional[Union[Command, Group]]:
        if not hasattr(ctx.bot, "command_list"):
            await _build_list(ctx)
        if cmd := ctx.bot.get_command(arg):
            return cmd
        match = closest_match(arg, [c.qualified_name for c in ctx.bot.walk_commands()])
        if match:
            return ctx.bot.get_command(match)
        raise CommandError(f"**can't** find a command named **{arg}**")


class AliasConverter(Converter):
    """convert comma string to Alias object"""
    async def convert(self, ctx: Context, arg: str) -> Optional[Alias]:
        if not hasattr(ctx.bot, "command_list"):
            await _build_list(ctx)
        if "," not in arg:
            raise CommandError("put a `,` between the command and alias")
        cmd_str, alias_str = [s.strip().lower() for s in arg.split(",", 1)]
        if alias_str in ctx.bot.command_list:
            raise CommandError(f"**can't** alias to **{alias_str}** its already a command")
        cmd = await CmdConverter().convert(ctx, cmd_str)
        return Alias(command=cmd, alias=alias_str)


async def handle_aliases(ctx: Context, aliases: List[Alias]) -> None:
    """swap alias back to real command and reprocess"""
    content = ctx.message.content.lower().replace(ctx.prefix, "")
    for a in aliases:
        if a.alias.lower() in content.split():
            ctx.message.content = ctx.message.content.replace(
                a.alias,
                a.command if isinstance(a.command, str) else a.command.qualified_name,
            )
            return await ctx.bot.process_commands(ctx.message)
