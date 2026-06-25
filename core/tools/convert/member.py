"""member converter with fuzzy name matching.
tries id mention username then fuzzy display name.
raises CommandError if no match found"""

from __future__ import annotations

from discord.ext.commands import Converter, CommandError, Context
from fast_string_match import closest_match
import discord


class MemberConvert(Converter):
    """convert string to guild Member"""
    async def convert(self, ctx: Context, arg: str) -> discord.Member:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")
        if isinstance(arg, discord.Member):
            return arg
        if isinstance(arg, discord.User):
            member = ctx.guild.get_member(arg.id)
            if member is not None:
                return member
            try:
                return await ctx.guild.fetch_member(arg.id)
            except discord.HTTPException:
                raise CommandError(f"**can't** find member **{arg}**")
        try:
            user_id = int(str(arg).strip("<@!>"))
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member
            try:
                return await ctx.guild.fetch_member(user_id)
            except discord.HTTPException:
                pass
        except (ValueError, TypeError):
            pass
        arg_low = str(arg).lower()
        for m in ctx.guild.members:
            if m.name.lower() == arg_low or m.display_name.lower() == arg_low:
                return m
        names = [m.display_name for m in ctx.guild.members]
        if match := closest_match(arg_low, names):
            return discord.utils.get(ctx.guild.members, display_name=match)
        raise CommandError(f"**can't** find member **{arg}**")

