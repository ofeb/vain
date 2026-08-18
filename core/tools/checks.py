"""permission checks for discord commands.
decorators that guard commands behind role or status checks.
use trusted guild_owner is_booster is_staff"""

from functools import wraps
from loguru import logger
import discord
from discord.ext.commands import CommandError, check, Context
from .errors import RolePosition


def trusted():
    """antinuke admin or owner only"""
    async def predicate(ctx: Context) -> bool:
        if ctx.author.id in ctx.bot.owners:
            return True
        admins = set(
            await ctx.bot.db.fetchval(
                "SELECT admins FROM antinuke WHERE guild_id = $1", ctx.guild.id
            ) or []
        )
        admins.add(ctx.guild.owner_id)
        if ctx.author.id not in admins:
            raise CommandError("You must be an **antinuke admin** to run this command.")
        return True
    return check(predicate)


def guild_owner():
    """guild owner or bot owner only"""
    async def predicate(ctx: Context) -> bool:
        if ctx.author.id == ctx.guild.owner_id or ctx.author.id in ctx.bot.owners:
            return True
        raise CommandError("You must be the **guild owner** to run this command.")
    return check(predicate)


def is_booster():
    """server booster or bot owner only"""
    async def predicate(ctx: Context) -> bool:
        if ctx.author.premium_since or ctx.author.id in ctx.bot.owners:
            return True
        raise CommandError("you **haven't** boosted the server")
    return check(predicate)


def is_staff():
    """bot owner only check"""
    async def predicate(ctx: Context) -> bool:
        return ctx.author.id in ctx.bot.owners
    return check(predicate)


def event_checks(func):
    """skip event handler if module or event is disabled in channel"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            bot = args[0].bot
            module = args[0].__class__.__name__.split("_Events", 1)[0].lower()
            guild = channel = None
            for arg in args:
                if isinstance(arg, discord.Member):
                    guild = arg.guild
                elif isinstance(arg, (discord.Message, Context)):
                    guild = arg.guild
                    channel = arg.channel
                elif isinstance(arg, discord.RawReactionActionEvent):
                    guild = bot.get_guild(arg.guild_id)
                    if guild:
                        channel = guild.get_channel(arg.channel_id)
            event = func.__cog_listener_names__[0] if hasattr(func, "__cog_listener_names__") else ""
            if guild and channel:
                if await bot.db.fetchrow(
                    "SELECT * FROM disabled_events WHERE guild_id = $1 AND event = $2",
                    guild.id, event
                ):
                    return logger.info(f"{event} disabled in {channel.name}")
                if await bot.db.fetchrow(
                    "SELECT * FROM disabled_modules WHERE guild_id = $1 AND module = $2",
                    guild.id, module
                ):
                    return logger.info(f"{module} disabled in {channel.name}")
        except Exception:
            pass
        return await func(*args, **kwargs)
    return wrapper
