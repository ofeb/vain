from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord

from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

DEFAULT_INVOKE_DM: dict[str, str] = {
    "ban": (
        "{embed}$v{title: You have been banned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}"
    ),
    "kick": (
        "{embed}$v{title: You have been kicked}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}"
    ),
    "softban": (
        "{embed}$v{title: You have been softbanned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}"
    ),
    "tempban": (
        "{embed}$v{title: You have been temporarily banned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "> **Duration:** {duration}\n"
        "-# Case **#{case_id}**}"
    ),
    "warn": (
        "{embed}$v{title: You received a warning}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}"
    ),
    "jail": (
        "{embed}$v{title: You have been jailed}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}"
    ),
    "unjail": (
        "{embed}$v{title: You have been unjailed}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}"
    ),
    "mute": (
        "{embed}$v{title: You have been muted}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "-# Case **#{case_id}**}"
    ),
    "unmute": (
        "{embed}$v{title: You have been unmuted}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}"
    ),
    "timeout": (
        "{embed}$v{title: You have been timed out}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}\n"
        "> **Duration:** {duration}}"
    ),
    "untimeout": (
        "{embed}$v{title: Your timeout was removed}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}"
    ),
    "unban": (
        "{embed}$v{title: You have been unbanned}$v"
        "{description: > **Server:** {guild.name}\n"
        "> **Staff:** {moderator.mention}\n"
        "> **Reason:** {reason}}"
    ),
}

DEFAULT_INVOKE_RESPONSE: dict[str, str] = {
    "ban": (
        "{container}$v{description: > -# **Banned** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "kick": (
        "{container}$v{description: > -# **Kicked** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "softban": (
        "{container}$v{description: > -# **Softbanned** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "tempban": (
        "{container}$v{description: > -# **Tempbanned** {user.mention}\n"
        "> -# **duration:** {duration}\n"
        "> -# **reason:** {reason}}"
    ),
    "warn": (
        "{container}$v{description: > -# **Warned** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "jail": (
        "{container}$v{description: > -# **Jailed** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "unjail": (
        "{container}$v{description: > -# **Unjailed** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "mute": (
        "{container}$v{description: > -# **Muted** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "unmute": (
        "{container}$v{description: > -# **Unmuted** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "timeout": (
        "{container}$v{description: > -# **Timed out** {user.mention}\n"
        "> -# **duration:** {duration}\n"
        "> -# **reason:** {reason}}"
    ),
    "untimeout": (
        "{container}$v{description: > -# **Timeout removed** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "unban": (
        "{container}$v{description: > -# **Unbanned** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
    "hardban": (
        "{container}$v{description: > -# **Hardbanned** {user.mention}\n"
        "> -# **reason:** {reason}}"
    ),
}



def build_modlog_embed(
    *,
    color: int | None = None,
    action: str,
    target_label: str,
    moderator_label: str,
    reason: str,
    case_id: int | None = None,
    extra: str | None = None,
) -> discord.Embed:
    """Build a compact C2-style modlog embed (no colour)."""
    _ = color
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
        color=None,
        lines=lines,
        footer=footer,
        timestamp=True,
    )


def build_security_log_embed(
    *,
    color: int | None = None,
    title: str,
    lines: list[str],
    footer: str | None = None,
) -> discord.Embed:
    """Build a compact C2-style security log embed (no colour)."""
    _ = color
    return panel_embed(
        color=None,
        title=title,
        lines=lines,
        footer=footer,
        timestamp=True,
    )


async def send_c2_embed(
    channel: discord.abc.Messageable,
    embed: discord.Embed,
    *,
    content: str | None = None,
    allowed_mentions: discord.AllowedMentions | None = None,
) -> discord.Message | None:
    """Send an embed as a Components V2 container (no accent colour).

    Falls back to a classic embed if the channel rejects LayoutView.
    """
    from core.discord.ctx import embed_to_layout

    mentions = allowed_mentions if allowed_mentions is not None else discord.AllowedMentions.none()
    try:
        layout = embed_to_layout(embed)
        kwargs: dict = {"view": layout, "allowed_mentions": mentions}
        if content is not None:
            kwargs["content"] = content
        return await channel.send(**kwargs)
    except Exception:
        kwargs = {"embed": embed, "allowed_mentions": mentions}
        if content is not None:
            kwargs["content"] = content
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            return await channel.send(**kwargs)
    return None


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
