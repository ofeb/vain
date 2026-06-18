"""color converter from hex or name string.
parses hex codes and css color names.
raises CommandError for invalid colors"""

from discord.ext.commands import Converter, CommandError, Context
import discord


class ColorConvert(Converter):
    """convert string to discord Color"""
    async def convert(self, ctx: Context, arg: str) -> discord.Color:
        arg = arg.strip().lstrip('#').lower()
        try:
            return discord.Color.from_str(f'#{arg}')
        except Exception:
            raise CommandError(f'**{arg}** isnt a valid color use hex like ff0000')
