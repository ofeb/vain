from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

import discord
from discord.ext.commands import CommandError

from core.tools.convert.member import _ID_RE, _MENTION_RE, resolve_member, resolve_user

_DURATION_RE = re.compile(r"^(\d+)([smhdwy])$", re.IGNORECASE)


@dataclass(slots=True)
class ParsedModerationArgs:
    member: discord.Member | None
    user: discord.User | None
    duration_seconds: int | None = None
    delete_days: int | None = None
    reason: str | None = None
    duration_before_member: bool = False


def command_tail(ctx, command_names: tuple[str, ...]) -> str:
    return _command_tail(ctx, command_names)


def _command_tail(ctx, command_names: tuple[str, ...]) -> str:
    content = (ctx.message.content or "").strip()
    if not content:
        return ""
    if ctx.prefix and content.startswith(ctx.prefix):
        content = content[len(ctx.prefix) :].strip()
    parts = content.split()
    if not parts:
        return ""
    idx = 0
    while idx < len(parts) and parts[idx].lower() in command_names:
        idx += 1
    return " ".join(parts[idx:]).strip()


def is_duration_token(token: str) -> bool:
    return bool(_DURATION_RE.match(str(token).strip().lower()))


def parse_duration_seconds(token: str) -> int | None:
    match = _DURATION_RE.match(str(token).strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
        "y": 31536000,
    }
    return amount * multipliers[unit]


def duration_to_delete_days(seconds: int) -> int:
    days = int(seconds / 86400)
    return max(0, min(days, 7))


def format_duration_token(seconds: int) -> str:
    for unit, mult in (("y", 31536000), ("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds % mult == 0:
            return f"{seconds // mult}{unit}"
    return f"{seconds}s"


def _duration_implies_tempban(token: str, *, before_member: bool) -> bool:
    match = _DURATION_RE.match(token.strip().lower())
    if not match:
        return False
    unit = match.group(2).lower()
    if unit in {"s", "m", "h", "y"}:
        return True
    if before_member:
        return True
    return False


def _extract_user_id(token: str) -> int | None:
    """Extract a user ID from a mention or raw ID string."""
    text = token.strip()
    m = _MENTION_RE.search(text)
    if m:
        return int(m.group(1))
    stripped = text.strip("<@!>")
    if _ID_RE.match(stripped):
        return int(stripped)
    if _ID_RE.match(text):
        return int(text)
    return None


async def _resolve_member(ctx, token: str) -> tuple[discord.Member | None, discord.User | None]:
    """Resolve a token to a Member (in-server) or User (anywhere).

    Returns (member, user) - member is set if the user is in the guild,
    user is always set if resolution succeeds.
    """
    user_id = _extract_user_id(token)

    if user_id is not None:
        if ctx.guild is not None:
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member, member

        if ctx.guild is not None:
            try:
                member = await ctx.guild.fetch_member(user_id)
                return member, member
            except discord.HTTPException:
                pass

        try:
            user = await ctx.bot.fetch_user(user_id)
            return None, user
        except discord.HTTPException:
            pass

        raise CommandError(f"**can't** find user **{token}**")

    if ctx.guild is not None:
        try:
            member = await resolve_member(ctx, token)
            return member, member
        except CommandError:
            pass

        try:
            uid, _label = await resolve_user(ctx, token)
            member = ctx.guild.get_member(uid)
            if member is not None:
                return member, member
            user = ctx.bot.get_user(uid)
            if user is not None:
                return None, user
            try:
                user = await ctx.bot.fetch_user(uid)
                return None, user
            except discord.HTTPException:
                pass
        except CommandError:
            pass

    raise CommandError(f"**can't** find member **{token}**")


async def _target_from_reply(ctx) -> tuple[discord.Member | None, discord.User | None]:
    """Resolve the replied-to message author as a mod target, if any."""
    msg = getattr(ctx, "message", None)
    if msg is None or not getattr(msg, "reference", None):
        return None, None
    ref = msg.reference
    resolved = getattr(ref, "resolved", None)
    author = None
    if isinstance(resolved, discord.Message):
        author = resolved.author
    else:
        mid = getattr(ref, "message_id", None)
        channel = getattr(ctx, "channel", None)
        if mid and channel is not None:
            try:
                fetched = await channel.fetch_message(mid)
                author = fetched.author
            except Exception:
                author = None
    if author is None or getattr(author, "bot", False):
        return None, None
    if ctx.guild is not None:
        member = ctx.guild.get_member(author.id)
        if member is None:
            try:
                member = await ctx.guild.fetch_member(author.id)
            except discord.HTTPException:
                member = None
        if member is not None:
            return member, member
    return None, author


async def parse_moderation_args(
    ctx,
    *,
    command_names: tuple[str, ...] = ("ban",),
    allow_duration: bool = True,
    allow_delete_days: bool = False,
) -> ParsedModerationArgs:
    """Parse ``[member] [duration] [reason…]`` or reply-target + ``[duration] [reason…]``.

    - Target: reply to their message, or username / id / mention
    - Duration (when allowed): optional token like ``2d`` / ``30m`` - first duration wins
    - Reason: optional remainder after target + duration
    - Jail / timeout with no duration → ``duration_seconds is None`` (indefinite)
    """
    tail = _command_tail(ctx, command_names)
    try:
        tokens = shlex.split(tail) if tail else []
    except ValueError:
        tokens = tail.split() if tail else []

    member: discord.Member | None = None
    user: discord.User | None = None
    member_index: int | None = None

    for index, token in enumerate(tokens):
        if is_duration_token(token):
            continue
        try:
            member, user = await _resolve_member(ctx, token)
            member_index = index
            break
        except CommandError:
            continue

    if member is None and user is None:
        member, user = await _target_from_reply(ctx)

    if member is None and user is None:
        raise CommandError("you must specify a member (mention, id, name, or reply)")

    duration_seconds: int | None = None
    delete_days: int | None = None
    duration_before_member = False
    consumed: set[int] = {member_index} if member_index is not None else set()

    if allow_duration or allow_delete_days:
        for index, token in enumerate(tokens):
            if index in consumed or not is_duration_token(token):
                continue
            seconds = parse_duration_seconds(token)
            if seconds is None:
                continue
            before_member = member_index is not None and index < member_index
            if allow_duration:
                if duration_seconds is None:
                    duration_seconds = seconds
                    duration_before_member = before_member
                    consumed.add(index)
            elif allow_delete_days and delete_days is None:
                delete_days = duration_to_delete_days(seconds)
                consumed.add(index)

    reason_tokens = [tokens[i] for i in range(len(tokens)) if i not in consumed]
    reason = " ".join(reason_tokens).strip() or None

    return ParsedModerationArgs(
        member=member,
        user=user,
        duration_seconds=duration_seconds,
        delete_days=delete_days,
        reason=reason,
        duration_before_member=duration_before_member,
    )


def parse_amount_and_reason(
    tail: str,
    *,
    max_amount: int = 100,
    default_amount: int | None = None,
) -> tuple[int, str | None]:
    tokens = tail.split()
    if not tokens:
        if default_amount is None:
            raise CommandError("you must provide an amount")
        return default_amount, None
    if not tokens[0].isdigit():
        raise CommandError("amount must be a number")
    amount = max(1, min(int(tokens[0]), max_amount))
    reason = " ".join(tokens[1:]).strip() or None
    return amount, reason
