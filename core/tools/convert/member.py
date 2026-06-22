"""member converter with fuzzy name matching.
tries id mention username then fuzzy display name.
raises CommandError if no match found"""

from discord.ext.commands import Converter, CommandError, Context
from fast_string_match import closest_match
import discord


class MemberConvert(Converter):
    """convert string to guild Member"""
    async def convert(self, ctx: Context, arg: str) -> discord.Member:
        try:
            user_id = int(arg.strip("<@!>"))
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member
            try:
                return await ctx.guild.fetch_member(user_id)
            except discord.HTTPException:
                pass
        except (ValueError, TypeError):
            pass
        arg_low = arg.lower()
        for m in ctx.guild.members:
            if m.name.lower() == arg_low or m.display_name.lower() == arg_low:
                return m
        names = [m.display_name for m in ctx.guild.members]
        if match := closest_match(arg, names):
            return discord.utils.get(ctx.guild.members, display_name=match)
        raise CommandError(f'cant find member **{arg}**')
