from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord

from core.tools.aesthetic import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

DEFAULT_INVOKE_DM: dict[str, str] = {
    "ban": (
        "{embed}$v{title: You have been banned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}$v{color: #E07A7A}"
    ),
    "kick": (
        "{embed}$v{title: You have been kicked}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}$v{color: #F5D76E}"
    ),
    "softban": (
        "{embed}$v{title: You have been softbanned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}$v{color: #E07A7A}"
    ),
    "tempban": (
        "{embed}$v{title: You have been temporarily banned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "> **Duration:** {duration}\n"
        "-# Case **#{case_id}**}$v{color: #E07A7A}"
    ),
    "warn": (
        "{embed}$v{title: You received a warning}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}$v{color: #F5D76E}"
    ),
    "jail": (
        "{embed}$v{title: You have been jailed}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}$v{color: #F5D76E}"
    ),
    "unjail": (
        "{embed}$v{title: You have been unjailed}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "mute": (
        "{embed}$v{title: You have been muted}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}$v{color: #F5D76E}"
    ),
    "unmute": (
        "{embed}$v{title: You have been unmuted}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "timeout": (
        "{embed}$v{title: You have been timed out}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "> **Duration:** {duration}}$v{color: #F5D76E}"
    ),
    "untimeout": (
        "{embed}$v{title: Your timeout was removed}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "unban": (
        "{embed}$v{title: You have been unbanned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
}

DEFAULT_INVOKE_RESPONSE: dict[str, str] = {
    "ban": (
        "{embed}$v{description: > -# **Banned** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "kick": (
        "{embed}$v{description: > -# **Kicked** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "softban": (
        "{embed}$v{description: > -# **Softbanned** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "tempban": (
        "{embed}$v{description: > -# **Tempbanned** {user.mention}\n"
        "> **Duration:** {duration}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "warn": (
        "{embed}$v{description: > -# **Warned** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "jail": (
        "{embed}$v{description: > -# **Jailed** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "unjail": (
        "{embed}$v{description: > -# **Unjailed** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "mute": (
        "{embed}$v{description: > -# **Muted** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "unmute": (
        "{embed}$v{description: > -# **Unmuted** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "timeout": (
        "{embed}$v{description: > -# **Timed out** {user.mention}\n"
        "> **Duration:** {duration}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "untimeout": (
        "{embed}$v{description: > -# **Timeout removed** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "unban": (
        "{embed}$v{description: > -# **Unbanned** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "hardban": (
        "{embed}$v{description: > -# **Hardbanned** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "imute": (
        "{embed}$v{description: > -# **Image muted** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "iunmute": (
        "{embed}$v{description: > -# **Image unmuted** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "rmute": (
        "{embed}$v{description: > -# **Reaction muted** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
    "runmute": (
        "{embed}$v{description: > -# **Reaction unmuted** {user.mention}\n"
        "> **Reason:** {reason}}$v{color: #A8D8A8}"
    ),
}


def build_modlog_embed(
    *,
    color: int,
    action: str,
    target_label: str,
    moderator_label: str,
    reason: str,
    case_id: int | None = None,
    extra: str | None = None,
) -> discord.Embed:
    lines = [
        f"**Action**: `{action}`",
        f"**Target**: {target_label}",
        f"**Moderator**: {moderator_label}",
        f"**Reason**: {reason}",
    ]
    if extra:
        lines.append(extra)
    footer = f"Case **#{case_id}**" if case_id is not None else None
    return panel_embed(
        color=color,
        lines=lines,
        footer=footer,
    )


def build_security_log_embed(
    *,
    color: int,
    title: str,
    lines: list[str],
    footer: str | None = None,
) -> discord.Embed:
    return panel_embed(
        color=color,
        title=title,
        lines=lines,
        footer=footer,
    )


async def fetch_invocation(db, guild_id: int, command: str):
    if getattr(db, "pool", None) is None:
        return None
    return await db.fetchrow(
        """SELECT dm_code, message_code, dm_enabled, message_enabled
           FROM invocation WHERE guild_id = $1 AND command = $2""",
        guild_id,
        command,
    )


async def send_invoke_dm(
    bot: Vain,
    db,
    *,
    member: discord.abc.User,
    guild: discord.Guild,
    moderator: discord.abc.User,
    action: str,
    reason: str | None,
    case_id: int | None = None,
    duration: str | None = None,
) -> bool:
    row = await fetch_invocation(db, guild.id, action)
    if row and row.get("dm_enabled") is False:
        return False
    script = (row["dm_code"] if row and row.get("dm_code") else None) or DEFAULT_INVOKE_DM.get(action)
    if not script:
        return False
    kwargs = {
        "user": member,
        "member": member,
        "moderator": moderator,
        "guild": guild,
        "reason": reason or "no reason provided",
        "case_id": case_id if case_id is not None else "N/A",
        "duration": duration or "N/A",
    }
    with contextlib.suppress(discord.Forbidden, discord.HTTPException, Exception):
        await bot.send_embed(member, script, **kwargs)
        return True
    return False


async def send_invoke_response(
    bot: Vain,
    db,
    ctx,
    *,
    action: str,
    user: discord.abc.User,
    moderator: discord.abc.User,
    reason: str | None,
    case_id: int | None = None,
    duration: str | None = None,
) -> bool:
    row = await fetch_invocation(db, ctx.guild.id, action)
    if row and row.get("message_enabled") is False:
        return False
    script = (row["message_code"] if row and row.get("message_code") else None) or DEFAULT_INVOKE_RESPONSE.get(action)
    if not script:
        return False
    kwargs = {
        "user": user,
        "member": user,
        "moderator": moderator,
        "guild": ctx.guild,
        "reason": reason or "no reason provided",
        "case_id": case_id if case_id is not None else "N/A",
        "duration": duration or "N/A",
        "ctx": ctx,
    }
    with contextlib.suppress(Exception):
        await bot.send_embed(ctx.channel, script, **kwargs)
        return True
    return False