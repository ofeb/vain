"""role converter with fuzzy name matching.
tries id mention then name then fuzzy match.
raises CommandError with closest suggestion"""

from discord.ext.commands import Converter, CommandError, Context
from fast_string_match import closest_match
import discord


class RoleConvert(Converter):
    """convert string to guild Role"""
    async def convert(self, ctx: Context, arg: str) -> discord.Role:
        try:
            role_id = int(arg.strip('<@&>'))
            if r := ctx.guild.get_role(role_id):
                return r
        except Exception:
            pass
        arg_low = arg.lower()
        if r := discord.utils.find(lambda r: r.name.lower() == arg_low, ctx.guild.roles):
            return r
        names = [r.name for r in ctx.guild.roles]
        if match := closest_match(arg, names):
            if r := discord.utils.get(ctx.guild.roles, name=match):
                return r
        raise CommandError(f"**can't** find role **{arg}**")
