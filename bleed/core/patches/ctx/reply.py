"""reply helper functions for context.
wraps ctx.reply with emoji prefixes from config.
use success fail warn functions"""

import discord
from discord.ext.commands import Context
from core.managers.values import emojis


def _emoji(name: str, fallback: str) -> str:
    emoji_dict = {
        'success': emojis.approve,
        'fail': emojis.deny,
        'warning': emojis.warn,
    }
    return emoji_dict.get(name, fallback)


async def success(ctx: Context, msg: str, **kw) -> discord.Message:
    """send green tick reply"""
    return await ctx.reply(f"{_emoji('success', 'OK')} {ctx.author.mention}: {msg}", **kw)

async def fail(ctx: Context, msg: str, **kw) -> discord.Message:
    """send red x reply"""
    return await ctx.reply(f"{_emoji('fail', 'X')} {ctx.author.mention}: {msg}", **kw)

async def warn(ctx: Context, msg: str, **kw) -> discord.Message:
    """send warning reply"""
    return await ctx.reply(f"{_emoji('warning', '!')} {ctx.author.mention}: {msg}", **kw)
