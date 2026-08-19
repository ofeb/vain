from __future__ import annotations

from typing import Any, Iterable, TypedDict

from config import emojis

_VALID_PUNISHMENTS = ("kick", "ban", "hardban", "softban", "timeout", "jail")
_DEFAULT_PUNISHMENTS = ["softban"]
_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
_MISSING: Any = object()
_DEFAULT_TRAP_SCRIPT = (
    "{container}"
    f"$v{{description: {emojis.warn} Don't send any messages here! {emojis.warn}}}"
    "$v{description: This channel is a **trap** for **compromised accounts**\n\nAnything posted here is **claimed as evidence** and the **compromised account** will be **softbanned**}"
    "$v{button: label: Caught: {honeypot.caught} && style: red && disabled: true}"
)


class Record(TypedDict, total=False):
    guild_id: int
    channel_id: int | None
    message_id: int | None
    alert_channel_id: int | None
    punishments: list[str]
    caught: int
    enabled: bool
    embed_script: str | None


def _normalize_punishments(raw: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        value = str(item or "").strip().lower()
        if value in {"hard"}:
            value = "hardban"
        if value not in _VALID_PUNISHMENTS or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out or list(_DEFAULT_PUNISHMENTS)


_PUNISHMENT_PAST = {
    "kick": "kicked",
    "ban": "banned",
    "hardban": "hardbanned",
    "softban": "softbanned",
    "timeout": "timed out",
    "jail": "jailed",
    "mute": "muted",
}


def _punishment_phrase(punishments: Iterable[str] | None) -> str:
    labels = [
        f"**{_PUNISHMENT_PAST.get(str(p).lower(), p)}**" for p in (punishments or [])
    ]
    if not labels:
        labels = ["**softbanned**"]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _comma(value: Any) -> str:
    """Format a number with thousands separators (human-friendly)."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _trap_body(punishments: Iterable[str] | None = None) -> str:
    """Trap copy with the warning emoji and a short description of the channel."""
    phrase = _punishment_phrase(_normalize_punishments(punishments))
    return "\n".join(
        [
            f"### {emojis.warn} DO NOT SEND MESSAGES HERE! {emojis.warn}",
            "",
            "This channel is a **trap** for **compromised accounts**.",
            "",
            f"Anything posted here is **claimed as evidence** and the **compromised account** will be {phrase}!",
        ]
    )


__all__ = [
    "_VALID_PUNISHMENTS",
    "_DEFAULT_PUNISHMENTS",
    "_TIMEOUT_SECONDS",
    "_MISSING",
    "_DEFAULT_TRAP_SCRIPT",
    "Record",
    "_normalize_punishments",
    "_punishment_phrase",
    "_comma",
    "_trap_body",
]
