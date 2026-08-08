from __future__ import annotations

import contextlib
from logging import getLogger
from typing import Any

from core.vain import Vain

from ..models import (
    _DEFAULT_PUNISHMENTS,
    _MISSING,
    _normalize_punishments,
)

logger = getLogger("vain.moderation.extended.honeypot.settings")


async def ensure_table(bot: Vain) -> None:
    """Create the `honeypot` table (and any missing columns) if needed."""
    if getattr(bot.db, "pool", None) is None:
        return
    with contextlib.suppress(Exception):
        await bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS honeypot (
                guild_id BIGINT PRIMARY KEY,
                channel_id BIGINT,
                message_id BIGINT,
                alert_channel_id BIGINT,
                punishments TEXT[] NOT NULL DEFAULT ARRAY['ban']::TEXT[],
                caught INT NOT NULL DEFAULT 0,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                embed_script TEXT
            )
            """
        )
    with contextlib.suppress(Exception):
        await bot.db.execute(
            "ALTER TABLE honeypot ADD COLUMN IF NOT EXISTS embed_script TEXT"
        )


async def fetch(bot: Vain, guild_id: int) -> dict[str, Any] | None:
    """Return the honeypot row for a guild, or None if unconfigured."""
    await ensure_table(bot)
    if getattr(bot.db, "pool", None) is None:
        return None
    row = await bot.db.fetchrow(
        "SELECT * FROM honeypot WHERE guild_id = $1",
        guild_id,
    )
    return dict(row) if row else None


async def upsert(
    bot: Vain,
    guild_id: int,
    *,
    channel_id: int | None = _MISSING,
    message_id: int | None = _MISSING,
    alert_channel_id: int | None = _MISSING,
    punishments: list[str] | None = None,
    caught: int | None = None,
    enabled: bool | None = None,
    embed_script: str | None = _MISSING,
) -> dict[str, Any]:
    """Insert or update the honeypot row, returning the resulting row."""
    await ensure_table(bot)
    current = await fetch(bot, guild_id) or {
        "guild_id": guild_id,
        "channel_id": None,
        "message_id": None,
        "alert_channel_id": None,
        "punishments": list(_DEFAULT_PUNISHMENTS),
        "caught": 0,
        "enabled": False,
        "embed_script": None,
    }

    next_channel = (
        current.get("channel_id") if channel_id is _MISSING else channel_id
    )
    next_message = (
        current.get("message_id") if message_id is _MISSING else message_id
    )
    next_alert = (
        current.get("alert_channel_id")
        if alert_channel_id is _MISSING
        else alert_channel_id
    )
    next_punishments = (
        _normalize_punishments(current.get("punishments"))
        if punishments is None
        else _normalize_punishments(punishments)
    )
    next_caught = int(current.get("caught") or 0) if caught is None else int(caught)
    next_enabled = bool(current.get("enabled")) if enabled is None else bool(enabled)
    next_script = (
        current.get("embed_script") if embed_script is _MISSING else embed_script
    )

    await bot.db.execute(
        """
        INSERT INTO honeypot (
            guild_id, channel_id, message_id, alert_channel_id,
            punishments, caught, enabled, embed_script
        )
        VALUES ($1, $2, $3, $4, $5::TEXT[], $6, $7, $8)
        ON CONFLICT (guild_id) DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            message_id = EXCLUDED.message_id,
            alert_channel_id = EXCLUDED.alert_channel_id,
            punishments = EXCLUDED.punishments,
            caught = EXCLUDED.caught,
            enabled = EXCLUDED.enabled,
            embed_script = EXCLUDED.embed_script
        """,
        guild_id,
        next_channel,
        next_message,
        next_alert,
        next_punishments,
        next_caught,
        next_enabled,
        next_script,
    )
    return {
        "guild_id": guild_id,
        "channel_id": next_channel,
        "message_id": next_message,
        "alert_channel_id": next_alert,
        "punishments": next_punishments,
        "caught": next_caught,
        "enabled": next_enabled,
        "embed_script": next_script,
    }


async def remove(bot: Vain, guild_id: int) -> None:
    """Delete the honeypot row for a guild."""
    await ensure_table(bot)
    await bot.db.execute(
        "DELETE FROM honeypot WHERE guild_id = $1",
        guild_id,
    )


__all__ = ["ensure_table", "fetch", "upsert", "remove"]
