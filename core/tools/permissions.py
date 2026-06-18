"""shared permission name helpers."""

from __future__ import annotations

_ALIASES = {
    "manage_emojis": "manage_expressions",
    "manage_emojis_and_stickers": "manage_expressions",
}

DANGEROUS_PERMISSIONS: tuple[str, ...] = (
    "administrator",
    "ban_members",
    "mention_everyone",
    "kick_members",
    "moderate_members",
    "manage_guild",
    "manage_channels",
    "manage_roles",
    "view_audit_log",
    "manage_webhooks",
    "manage_expressions",
    "manage_nicknames",
)


def normalize_dangerous_permission(value: str) -> str | None:
    """normalize a permission label and reject unsupported values."""
    normalized = value.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = _ALIASES.get(normalized, normalized)
    if normalized in DANGEROUS_PERMISSIONS:
        return normalized
    return None
