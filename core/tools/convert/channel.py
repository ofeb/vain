"""channel converter with fuzzy name matching.
tries mention id then exact then fuzzy name.
raises CommandError if no match found"""

from discord.ext.commands import Converter, CommandError, Context
from fast_string_match import closest_match
from typing import Union
import discord


class ChannelConvert(Converter):
    """convert string to any guild channel"""
    async def convert(self, ctx: Context, arg: str):
        try:
            cid = int(arg.strip('<#>'))
            if ch := ctx.guild.get_channel(cid):
                return ch
        except Exception:
            pass
        arg_low = arg.lower()
        for ch in ctx.guild.channels:
            if ch.name.lower() == arg_low:
                return ch
        names = [ch.name for ch in ctx.guild.channels]
        if match := closest_match(arg, names):
            if ch := discord.utils.get(ctx.guild.channels, name=match):
                return ch
        raise CommandError(f'cant find channel **{arg}**')
