"""color converter from hex or name string.
parses hex codes and css color names.
raises CommandError for invalid colors"""

from discord.ext.commands import Converter, CommandError, Context
import discord


class ColorConvert(Converter):
    """convert string to discord Color"""
    async def convert(self, ctx: Context, arg: str) -> discord.Color:
        raw = (arg or "").strip()
        # auto-prefix # for bare hex
        h = raw[1:] if raw.startswith("#") else raw
        h = h.lower()
        try:
            if len(h) == 3 and all(c in "0123456789abcdef" for c in h):
                h = "".join(c * 2 for c in h)
            color = discord.Color.from_str(f"#{h}")
        except Exception:
            raise CommandError(f"**{arg}** isnt a valid color use hex like ff0000")
        # pure black (#000000) is Discord's "default" / invisible role colour — bump to #000001
        if color.value == 0:
            color = discord.Color(1)
        return color
