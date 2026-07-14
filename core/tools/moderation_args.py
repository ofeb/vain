from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

import discord
from discord.ext.commands import CommandError

from core.tools.convert import MemberConvert

_DURATION_RE = re.compile(r"^(\d+)([smhdwy])$", re.IGNORECASE)
_MENTION_RE = re.compile(r"<@!?(\d+)>")
_ID_RE = re.compile(r"^\d{15,20}$")


@dataclass(slots=True)
class ParsedModerationArgs:
    member: discord.Member
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


async def _resolve_member(ctx, token: str) -> discord.Member:
    return await MemberConvert().convert(ctx, token)


async def parse_moderation_args(
    ctx,
    *,
    command_names: tuple[str, ...] = ("ban",),
    allow_duration: bool = True,
    allow_delete_days: bool = False,
) -> ParsedModerationArgs:
    tail = _command_tail(ctx, command_names)
    if not tail:
        raise CommandError("you must specify a member")

    try:
        tokens = shlex.split(tail)
    except ValueError:
        tokens = tail.split()

    if not tokens:
        raise CommandError("you must specify a member")

    member: discord.Member | None = None
    member_index: int | None = None
    for index, token in enumerate(tokens):
        if is_duration_token(token):
            continue
        try:
            member = await _resolve_member(ctx, token)
            member_index = index
            break
        except CommandError:
            continue

    if member is None or member_index is None:
        raise CommandError("could not find that member")

    duration_seconds: int | None = None
    delete_days: int | None = None
    duration_before_member = False
    consumed: set[int] = {member_index}

    if allow_duration or allow_delete_days:
        for index, token in enumerate(tokens):
            if index in consumed or not is_duration_token(token):
                continue
            seconds = parse_duration_seconds(token)
            if seconds is None:
                continue
            before_member = index < member_index
            if allow_duration and _duration_implies_tempban(token, before_member=before_member):
                duration_seconds = seconds
                duration_before_member = before_member
                consumed.add(index)
            elif allow_delete_days and not duration_seconds:
                delete_days = duration_to_delete_days(seconds)
                consumed.add(index)

    reason_tokens = [tokens[i] for i in range(len(tokens)) if i not in consumed]
    reason = " ".join(reason_tokens).strip() or None

    return ParsedModerationArgs(
        member=member,
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