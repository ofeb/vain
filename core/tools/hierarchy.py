"""Role hierarchy checks for member-targeting commands.

Used so moderators cannot act on members with equal or higher roles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext.commands import CommandError

if TYPE_CHECKING:
    from discord.ext.commands import Context


def is_member_like(obj: object) -> bool:
    """True for guild members / users (people), not channels."""
    if obj is None:
        return False
    
    if isinstance(obj, (discord.abc.GuildChannel, discord.Thread)):
        return False
    if isinstance(obj, discord.Member):
        return True
    if isinstance(obj, discord.User):
        return True
    
    if hasattr(obj, "roles") and hasattr(obj, "guild_permissions"):
        if hasattr(obj, "type") and not hasattr(obj, "display_name"):
            return False
        return True
    return False


def target_preposition(target: object) -> str:
    """``for`` a person, ``in`` a channel/place."""
    return "for" if is_member_like(target) else "in"


def target_phrase(target: object) -> str:
    mention = getattr(target, "mention", str(target))
    return f"{target_preposition(target)} {mention}"


def hierarchy_error_message(member: discord.Member) -> str:
    return (
        f"you need a **higher** role than {member.mention} "
        f"to be able to do that!"
    )


def check_member_hierarchy(
    ctx: Context,
    member: discord.Member,
    *,
    allow_self: bool = False,
    bot_hierarchy: bool = True,
) -> str | None:
    """Return an error string if *author* cannot act on *member*, else ``None``.

    Parameters
    ----------
    bot_hierarchy:
        When True (default), also require the bot's top role to be above the
        target. Use True for moderation actions the bot performs on Discord
        (kick/ban/timeout/roles). Use False for config-only actions that only
        write to the database (disablecommand, ignore, allow, …).
    """
    guild = getattr(ctx, "guild", None)
    author = getattr(ctx, "author", None)
    if guild is None or member is None:
        return None

    if not isinstance(member, discord.Member):
        
        resolved = guild.get_member(getattr(member, "id", 0))
        if resolved is not None:
            member = resolved
        elif not hasattr(member, "top_role"):
            return None

    if not allow_self and author and member.id == author.id:
        return "you **can't** do that to yourself!"

    if member.id == guild.owner_id and (not author or author.id != guild.owner_id):
        bot = getattr(ctx, "bot", None)
        if bot is None or author is None or author.id not in getattr(bot, "owners", set()):
            return hierarchy_error_message(member)

    author_top = getattr(author, "top_role", None) if author is not None else None
    member_top = getattr(member, "top_role", None)
    if (
        author is not None
        and author_top is not None
        and member_top is not None
        and getattr(author, "id", None) != guild.owner_id
    ):
        try:
            if member_top >= author_top:
                return hierarchy_error_message(member)
        except TypeError:
            return hierarchy_error_message(member)

    if bot_hierarchy:
        bot_user = getattr(getattr(ctx, "bot", None), "user", None)
        bot_member = guild.me or (guild.get_member(bot_user.id) if bot_user else None)
        if bot_member is not None and member.id != getattr(bot_member, "id", None):
            bot_top = getattr(bot_member, "top_role", None)
            if bot_top is not None and member_top is not None:
                try:
                    if member_top >= bot_top:
                        return (
                            f"I need a **higher** role than {member.mention} "
                            f"to be able to do that!"
                        )
                except TypeError:
                    return (
                        f"I need a **higher** role than {member.mention} "
                        f"to be able to do that!"
                    )

    return None


async def ensure_member_hierarchy(
    ctx: Context,
    member: discord.Member,
    *,
    allow_self: bool = False,
    bot_hierarchy: bool = True,
) -> None:
    """Raise ``CommandError`` when hierarchy blocks the action."""
    bot = getattr(ctx, "bot", None)
    author = getattr(ctx, "author", None)
    if bot is not None and author is not None:
        try:
            if await bot.is_owner(author):
                
                
                if bot_hierarchy:
                    guild = ctx.guild
                    if guild is not None:
                        resolved = member
                        if not isinstance(resolved, discord.Member):
                            resolved = guild.get_member(getattr(member, "id", 0))
                        bot_member = guild.me or (
                            guild.get_member(bot.user.id) if bot.user else None
                        )
                        if (
                            resolved is not None
                            and bot_member is not None
                            and resolved.id != bot_member.id
                            and getattr(resolved, "top_role", None) is not None
                            and resolved.top_role >= bot_member.top_role
                        ):
                            raise CommandError(
                                f"I need a **higher** role than {resolved.mention} "
                                f"to be able to do that!"
                            )
                return
        except CommandError:
            raise
        except Exception:
            pass

    msg = check_member_hierarchy(
        ctx,
        member,
        allow_self=allow_self,
        bot_hierarchy=bot_hierarchy,
    )
    if msg:
        raise CommandError(msg)
