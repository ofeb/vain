"""Giveaway entry requirements - parse, display, and enforce."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import ActivityType, CustomActivity





REQUIREMENT_CATALOG: list[dict[str, str]] = [
    {
        "key": "level",
        "usage": "level <n>",
        "summary": "Need server level **n** or higher (leveling must be on).",
    },
    {
        "key": "boosting",
        "usage": "boosting",
        "summary": "Must be boosting this server right now.",
    },
    {
        "key": "role",
        "usage": "role <role>",
        "summary": "Must have the given role to join.",
    },
    {
        "key": "accountage",
        "usage": "accountage <days>",
        "summary": "Discord account must be at least **n** days old.",
    },
    {
        "key": "serverage",
        "usage": "serverage <days>",
        "summary": "Must have been in this server for at least **n** days.",
    },
    {
        "key": "badge",
        "usage": "badge",
        "summary": "Must show this server’s clan/tag badge on their profile.",
    },
    {
        "key": "vanity",
        "usage": "vanity",
        "summary": "Custom status must include the server vanity (e.g. `/bars`).",
    },
    {
        "key": "status",
        "usage": "status",
        "summary": "Must have any custom status set.",
    },
    {
        "key": "vc",
        "usage": "vc",
        "summary": "Must be connected to a voice channel here.",
    },
    {
        "key": "voiceamount",
        "usage": "voiceamount <minutes>",
        "summary": "Must have spent at least **n** minutes in voice here.",
    },
    {
        "key": "nodeaf",
        "usage": "nodeaf",
        "summary": "If in voice, must not be deafened (self or server).",
    },
    {
        "key": "message",
        "usage": "message <count>",
        "summary": "Must have sent at least **n** messages in this server.",
    },
    {
        "key": "participation",
        "usage": "participation <count>",
        "summary": "Must send **n** messages in this server **after** the giveaway starts.",
    },
    {
        "key": "invites",
        "usage": "invites <count>",
        "summary": "Must have at least **n** successful invites (joins that stuck).",
    },
]

_CATALOG_BY_KEY = {c["key"]: c for c in REQUIREMENT_CATALOG}


_KEY_ALIASES: dict[str, str] = {
    "level": "level",
    "lvl": "level",
    "boosting": "boosting",
    "boost": "boosting",
    "booster": "boosting",
    "role": "role",
    "roles": "role",
    "accountage": "accountage",
    "account": "accountage",
    "accage": "accountage",
    "serverage": "serverage",
    "memberage": "serverage",
    "badge": "badge",
    "tag": "badge",
    "clantag": "badge",
    "vanity": "vanity",
    "status": "status",
    "customstatus": "status",
    "vc": "vc",
    "voice": "vc",
    "voicechannel": "vc",
    "voiceamount": "voiceamount",
    "voicetime": "voiceamount",
    "vcminutes": "voiceamount",
    "nodeaf": "nodeaf",
    "undeaf": "nodeaf",
    "message": "message",
    "messages": "message",
    "msgs": "message",
    "participation": "participation",
    "active": "participation",
    "invites": "invites",
    "invite": "invites",
}

_FLAG_SPLIT = re.compile(r"(?:^|\s)--(?=\w)")
_WINNERS_RE = re.compile(r"(?i)^(?:winners?|w)\s+(\d+)$")
_REQ_HEAD_RE = re.compile(r"(?i)^(?:requirement|req|r)\s+(.+)$", re.DOTALL)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def empty_requirements() -> dict[str, Any]:
    return {
        "min_level": None,
        "required_roles": [],
        "boosting": False,
        "account_age_days": None,
        "server_age_days": None,
        "badge": False,
        "vanity": False,
        "status": False,
        "vc": False,
        "voice_minutes": None,
        "no_deaf": False,
        "message_count": None,
        "participation": None,
        "invites": None,
    }


def requirements_from_record(record: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a DB row (or flat requirements dict) into a requirements map."""
    base = empty_requirements()
    if not record:
        return base

    def _merge(src: dict[str, Any]) -> None:
        for k in base:
            if k in src and src[k] is not None:
                base[k] = src[k]

    
    raw = record.get("requirements")
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except Exception:
            raw = None
    if isinstance(raw, dict):
        _merge(raw)

    
    _merge(record)

    
    if base["required_roles"] is None:
        base["required_roles"] = []
    try:
        base["required_roles"] = [int(x) for x in base["required_roles"] if x is not None]
    except Exception:
        base["required_roles"] = []
    for flag in ("boosting", "badge", "vanity", "status", "vc", "no_deaf"):
        base[flag] = bool(base.get(flag))
    for num_key in (
        "min_level",
        "account_age_days",
        "server_age_days",
        "voice_minutes",
        "message_count",
        "participation",
        "invites",
    ):
        val = base.get(num_key)
        if val is None or val == "" or val is False:
            base[num_key] = None
        else:
            try:
                base[num_key] = int(val)
            except Exception:
                base[num_key] = None
    return base


def format_requirements(reqs: dict[str, Any], *, guild: discord.Guild | None = None) -> list[str]:
    """Human-readable requirement lines for panels / help."""
    r = requirements_from_record(reqs if isinstance(reqs, dict) else {})
    lines: list[str] = []
    if r.get("min_level") is not None:
        lines.append(f"server level **{r['min_level']}+**")
    if r.get("boosting"):
        lines.append("must be **boosting** this server")
    for rid in r.get("required_roles") or []:
        role = guild.get_role(int(rid)) if guild else None
        lines.append(f"role {role.mention if role else f'<@&{rid}>'}")
    if r.get("account_age_days") is not None:
        d = int(r["account_age_days"])
        lines.append(f"account age **{d}** day{'s' if d != 1 else ''}+")
    if r.get("server_age_days") is not None:
        d = int(r["server_age_days"])
        lines.append(f"in server **{d}** day{'s' if d != 1 else ''}+")
    if r.get("badge"):
        lines.append("server **badge / clan tag** on profile")
    if r.get("vanity"):
        code = getattr(guild, "vanity_url_code", None) if guild else None
        if code:
            lines.append(f"vanity **/{code}** in status")
        else:
            lines.append("server **vanity** in status")
    if r.get("status"):
        lines.append("any **custom status**")
    if r.get("vc"):
        lines.append("connected to a **voice channel**")
    if r.get("voice_minutes") is not None:
        m = int(r["voice_minutes"])
        lines.append(f"**{m}** min in voice here")
    if r.get("no_deaf"):
        lines.append("not **deafened** in voice")
    if r.get("message_count") is not None:
        n = int(r["message_count"])
        lines.append(f"**{n}** message{'s' if n != 1 else ''} sent here")
    if r.get("participation") is not None:
        n = int(r["participation"])
        lines.append(f"**{n}** message{'s' if n != 1 else ''} after giveaway starts")
    if r.get("invites") is not None:
        n = int(r["invites"])
        lines.append(f"**{n}** successful invite{'s' if n != 1 else ''}")
    return lines


def catalog_lines() -> list[str]:
    out: list[str] = []
    for i, item in enumerate(REQUIREMENT_CATALOG, 1):
        out.append(
            f"`{i:02d}` **{item['usage']}** - {item['summary']}"
        )
    return out


def _parse_int(token: str) -> int | None:
    t = (token or "").strip().lower().rstrip("s")
    if t.isdigit():
        return int(t)
    
    m = re.fullmatch(r"(\d+)d(?:ay)?s?", t)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(\d+)h(?:our)?s?", t)
    if m:
        
        return max(1, (int(m.group(1)) + 23) // 24)
    return None


async def _resolve_role(ctx, token: str) -> discord.Role | None:
    raw = (token or "").strip()
    if not raw or not ctx.guild:
        return None
    
    m = re.fullmatch(r"<@&(\d+)>", raw)
    if m:
        role = ctx.guild.get_role(int(m.group(1)))
        if role:
            return role
    if raw.isdigit():
        role = ctx.guild.get_role(int(raw))
        if role:
            return role
    
    low = raw.lower().lstrip("@")
    for role in ctx.guild.roles:
        if role.name.lower() == low:
            return role
    for role in ctx.guild.roles:
        if low in role.name.lower():
            return role
    try:
        from discord.ext.commands import RoleConverter

        return await RoleConverter().convert(ctx, raw)
    except Exception:
        return None


async def parse_requirement_chunk(ctx, chunk: str, dest: dict[str, Any]) -> None:
    """Apply one requirement token group into *dest* (mutates).

    Accepts forms like:
      level 5
      boosting
      role Members
      accountage 30
      level 5, badge
    """
    from discord.ext.commands import BadArgument

    text = (chunk or "").strip()
    if not text:
        return

    
    pieces = [p.strip() for p in re.split(r"\s*,\s*", text) if p.strip()]
    for piece in pieces:
        tokens = piece.split()
        if not tokens:
            continue
        key_raw = tokens[0].lower().lstrip("-")
        key = _KEY_ALIASES.get(key_raw)
        if key is None:
            raise BadArgument(
                f"Unknown requirement **{tokens[0]}**. "
                f"See {ctx.cmd('giveaway requirements')} for the full list."
            )
        rest = tokens[1:]

        if key == "level":
            if not rest:
                raise BadArgument("Usage: `--requirement level <n>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Level must be a positive number.")
            dest["min_level"] = n
        elif key == "boosting":
            dest["boosting"] = True
        elif key == "role":
            if not rest:
                raise BadArgument("Usage: `--requirement role <role>`")
            role = await _resolve_role(ctx, " ".join(rest))
            if role is None:
                raise BadArgument(f"Could not find role **{' '.join(rest)}**.")
            roles = list(dest.get("required_roles") or [])
            if role.id not in roles:
                roles.append(role.id)
            dest["required_roles"] = roles
        elif key == "accountage":
            if not rest:
                raise BadArgument("Usage: `--requirement accountage <days>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Account age must be a positive number of days.")
            dest["account_age_days"] = n
        elif key == "serverage":
            if not rest:
                raise BadArgument("Usage: `--requirement serverage <days>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Server age must be a positive number of days.")
            dest["server_age_days"] = n
        elif key == "badge":
            dest["badge"] = True
        elif key == "vanity":
            dest["vanity"] = True
        elif key == "status":
            dest["status"] = True
        elif key == "vc":
            dest["vc"] = True
        elif key == "voiceamount":
            if not rest:
                raise BadArgument("Usage: `--requirement voiceamount <minutes>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Voice time must be a positive number of minutes.")
            dest["voice_minutes"] = n
        elif key == "nodeaf":
            dest["no_deaf"] = True
        elif key == "message":
            if not rest:
                raise BadArgument("Usage: `--requirement message <count>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Message count must be a positive number.")
            dest["message_count"] = n
        elif key == "participation":
            if not rest:
                raise BadArgument("Usage: `--requirement participation <count>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Participation count must be a positive number.")
            dest["participation"] = n
        elif key == "invites":
            if not rest:
                raise BadArgument("Usage: `--requirement invites <count>`")
            n = _parse_int(rest[0])
            if n is None or n < 1:
                raise BadArgument("Invite count must be a positive number.")
            dest["invites"] = n


def split_start_payload(raw: str) -> tuple[str, list[str]]:
    """Split start args into main body and `--flag …` chunks."""
    text = (raw or "").strip()
    if not text:
        return "", []
    parts = _FLAG_SPLIT.split(text)
    body = (parts[0] or "").strip()
    flags = [p.strip() for p in parts[1:] if p and p.strip()]
    return body, flags


async def apply_start_flags(ctx, flags: list[str]) -> tuple[int | None, dict[str, Any]]:
    """Return (winners override or None, requirements dict)."""
    from discord.ext.commands import BadArgument

    winners: int | None = None
    reqs = empty_requirements()
    for flag in flags:
        m = _WINNERS_RE.match(flag.strip())
        if m:
            winners = max(1, int(m.group(1)))
            continue
        m = _REQ_HEAD_RE.match(flag.strip())
        if m:
            await parse_requirement_chunk(ctx, m.group(1), reqs)
            continue
        
        head = flag.split()[0].lower() if flag.split() else flag
        raise BadArgument(
            f"Unknown flag `--{head}`. "
            f"Use `--winners <n>` or `--requirement <type> [value]`."
        )
    return winners, reqs


def has_any_requirement(reqs: dict[str, Any]) -> bool:
    r = requirements_from_record(reqs)
    if r.get("min_level") is not None:
        return True
    if r.get("required_roles"):
        return True
    if r.get("boosting") or r.get("badge") or r.get("vanity") or r.get("status"):
        return True
    if r.get("vc") or r.get("no_deaf"):
        return True
    for k in (
        "account_age_days",
        "server_age_days",
        "voice_minutes",
        "message_count",
        "participation",
        "invites",
    ):
        if r.get(k) is not None:
            return True
    return False


def _custom_status_texts(member: discord.Member) -> list[str]:
    parts: list[str] = []
    activities = list(getattr(member, "activities", None) or ())
    primary = getattr(member, "activity", None)
    if primary is not None and primary not in activities:
        activities.insert(0, primary)
    for activity in activities:
        if activity is None:
            continue
        atype = getattr(activity, "type", None)
        is_custom = (
            isinstance(activity, CustomActivity)
            or atype is ActivityType.custom
            or getattr(atype, "name", None) == "custom"
            or int(getattr(atype, "value", -1)) == 4
        )
        if not is_custom:
            continue
        for attr in ("state", "name", "details"):
            val = getattr(activity, attr, None)
            if not val:
                continue
            text = str(val).strip()
            if not text or text.lower() in {"custom status", "customstatus"}:
                continue
            parts.append(text)
    return parts


def _has_guild_badge(member: discord.Member) -> bool:
    """True if member's primary guild / clan tag matches this guild."""
    guild = member.guild
    pg = getattr(member, "primary_guild", None)
    if pg is None:
        
        return False
    gid = getattr(pg, "identity_guild_id", None) or getattr(pg, "id", None)
    if gid is not None and int(gid) == int(guild.id):
        
        enabled = getattr(pg, "identity_enabled", None)
        if enabled is False:
            return False
        return True
    
    return False


async def check_member_requirements(
    bot,
    member: discord.Member,
    reqs: dict[str, Any],
    *,
    giveaway: dict[str, Any] | None = None,
    enforce_participation: bool = True,
) -> tuple[bool, str | None]:
    """Return (ok, fail_reason). fail_reason is user-facing when not ok.

    *enforce_participation* - set False on join so members can enter first and
    farm the post-start message count before the draw; still enforced at end.
    """
    r = requirements_from_record(reqs if isinstance(reqs, dict) else {})
    if giveaway:
        
        r = requirements_from_record({**r, **{k: giveaway.get(k) for k in (
            "min_level", "required_roles", "requirements"
        )}})
        if isinstance(giveaway.get("requirements"), dict):
            r = requirements_from_record({**requirements_from_record(giveaway), **giveaway["requirements"]})

    guild = member.guild

    
    if r.get("min_level") is not None:
        level = None
        for query in (
            "SELECT level FROM level_user WHERE user_id = $1 AND guild_id = $2",
            "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
        ):
            try:
                level = await bot.db.fetchval(query, member.id, guild.id)
                if level is not None:
                    break
            except Exception:
                continue
        try:
            level_i = int(level or 0)
        except Exception:
            level_i = 0
        if level_i < int(r["min_level"]):
            return False, f"you need server level **{r['min_level']}+** (you’re **{level_i}**)"

    
    needed = set(int(x) for x in (r.get("required_roles") or []))
    if needed:
        have = {role.id for role in member.roles}
        if not (have & needed):
            mentions = ", ".join(f"<@&{rid}>" for rid in needed)
            return False, f"you need one of these roles: {mentions}"

    
    if r.get("boosting") and not getattr(member, "premium_since", None):
        return False, "you must be **boosting** this server"

    
    if r.get("account_age_days") is not None:
        created = _as_aware(member.created_at)
        if created is None or (_now_utc() - created) < timedelta(days=int(r["account_age_days"])):
            return False, f"your Discord account must be at least **{r['account_age_days']}** days old"

    
    if r.get("server_age_days") is not None:
        joined = _as_aware(getattr(member, "joined_at", None))
        if joined is None or (_now_utc() - joined) < timedelta(days=int(r["server_age_days"])):
            return False, f"you must have been in this server for **{r['server_age_days']}+** days"

    
    if r.get("badge") and not _has_guild_badge(member):
        return False, "set this server’s **badge / clan tag** on your profile"

    
    if r.get("vanity"):
        code = (getattr(guild, "vanity_url_code", None) or "").strip()
        if not code:
            return False, "this server has no vanity set for the vanity requirement"
        texts = " ".join(_custom_status_texts(member)).lower()
        needles = {code.lower(), f"/{code.lower()}", f".gg/{code.lower()}", f"discord.gg/{code.lower()}"}
        if not any(n in texts for n in needles):
            return False, f"put **/{code}** in your custom status"

    
    if r.get("status") and not _custom_status_texts(member):
        return False, "set a **custom status** to enter"

    
    voice = getattr(member, "voice", None)
    if r.get("vc"):
        if voice is None or voice.channel is None:
            return False, "join a **voice channel** in this server"

    
    if r.get("no_deaf"):
        if voice is None or voice.channel is None:
            return False, "join voice **undeafened** to enter"
        if getattr(voice, "self_deaf", False) or getattr(voice, "deaf", False):
            return False, "undeafen in voice to enter"

    
    if r.get("voice_minutes") is not None:
        mins = 0
        try:
            mins = int(
                await bot.db.fetchval(
                    """
                    SELECT COALESCE(minutes, 0) FROM giveaway_voice_stats
                    WHERE guild_id = $1 AND user_id = $2
                    """,
                    guild.id,
                    member.id,
                )
                or 0
            )
        except Exception:
            mins = 0
        
        try:
            joined = await bot.db.fetchval(
                """
                SELECT joined_at FROM giveaway_voice_sessions
                WHERE guild_id = $1 AND user_id = $2
                """,
                guild.id,
                member.id,
            )
            if joined is not None:
                if getattr(joined, "tzinfo", None) is not None:
                    joined = joined.astimezone(timezone.utc).replace(tzinfo=None)
                live = max(0, int((_now_utc().replace(tzinfo=None) - joined).total_seconds() // 60))
                mins += live
            elif voice is not None and voice.channel is not None:
                
                pass
        except Exception:
            pass
        need = int(r["voice_minutes"])
        if mins < need:
            return False, f"you need **{need}** min in voice here (you have **{mins}**)"

    
    if r.get("message_count") is not None:
        count = 0
        try:
            count = int(
                await bot.db.fetchval(
                    """
                    SELECT COALESCE(count, 0) FROM giveaway_message_stats
                    WHERE guild_id = $1 AND user_id = $2
                    """,
                    guild.id,
                    member.id,
                )
                or 0
            )
        except Exception:
            count = 0
        need = int(r["message_count"])
        if count < need:
            return False, f"you need **{need}** messages sent here (you have **{count}**)"

    
    if (
        enforce_participation
        and r.get("participation") is not None
        and giveaway is not None
    ):
        message_id = int(giveaway.get("message_id") or 0)
        count = 0
        try:
            count = int(
                await bot.db.fetchval(
                    """
                    SELECT COALESCE(count, 0) FROM giveaway_participation
                    WHERE message_id = $1 AND user_id = $2
                    """,
                    message_id,
                    member.id,
                )
                or 0
            )
        except Exception:
            count = 0
        need = int(r["participation"])
        if count < need:
            return False, (
                f"send **{need}** messages here after the giveaway started "
                f"(you have **{count}**)"
            )

    
    if r.get("invites") is not None:
        real = 0
        try:
            row = await bot.db.fetchrow(
                "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
                guild.id,
                member.id,
            )
            if row:
                data = dict(row)
                real = int(data.get("invites") or 0) - int(data.get("leaves") or 0) - int(
                    data.get("fake") or 0
                ) + int(data.get("bonus") or 0)
        except Exception:
            real = 0
        need = int(r["invites"])
        if real < need:
            return False, f"you need **{need}** successful invites (you have **{max(0, real)}**)"

    return True, None


__all__ = [
    "REQUIREMENT_CATALOG",
    "apply_start_flags",
    "catalog_lines",
    "check_member_requirements",
    "empty_requirements",
    "format_requirements",
    "has_any_requirement",
    "parse_requirement_chunk",
    "requirements_from_record",
    "split_start_payload",
]
