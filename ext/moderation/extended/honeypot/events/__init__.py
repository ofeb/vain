from __future__ import annotations

import contextlib
import time

import discord

from core.discord.package import Package

from ..models import _normalize_punishments
from ..settings import fetch, upsert


class HoneypotEvents(Package):
    """Watches guild messages and triggers the honeypot trap."""

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._honeypot_cache: dict[int, dict] = {}
        self._honeypot_cache_ttl: float = 30.0
        self._honeypot_last_fetch: dict[int, float] = {}

    async def _get_honeypot_config(self, guild_id: int) -> dict | None:
        """Get honeypot config with caching to reduce DB queries."""
        now = time.monotonic()
        last = self._honeypot_last_fetch.get(guild_id, 0)
        if now - last < self._honeypot_cache_ttl and guild_id in self._honeypot_cache:
            return self._honeypot_cache[guild_id]
        row = await fetch(self.bot, guild_id)
        self._honeypot_cache[guild_id] = row or {}
        self._honeypot_last_fetch[guild_id] = now
        return row

    def _invalidate_cache(self, guild_id: int) -> None:
        """Invalidate cache for a guild."""
        self._honeypot_cache.pop(guild_id, None)
        self._honeypot_last_fetch.pop(guild_id, None)

    @Package.listener("on_message")
    async def on_honeypot_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return
        if getattr(self.db, "pool", None) is None:
            return

        row = await self._get_honeypot_config(message.guild.id)
        if not row or not row.get("enabled") or not row.get("channel_id"):
            return
        if int(message.channel.id) != int(row["channel_id"]):
            return

        if message.id == row.get("message_id"):
            return
        if self._is_exempt(message.author):
            return

        reason = f"Honeypot triggered in #{getattr(message.channel, 'name', 'honeypot')}"
        author = message.author
        content = message.content or ""
        attachment_count = len(message.attachments or [])
        channel_mention = getattr(message.channel, "mention", None) or f"`{message.channel.id}`"

        with contextlib.suppress(discord.Forbidden, discord.HTTPException, discord.NotFound):
            await message.delete()

        punishments = _normalize_punishments(row.get("punishments"))

        applied = await self._apply_punishments(author, punishments, reason=reason)

        caught = int(row.get("caught") or 0) + 1
        updated = await upsert(self.bot, message.guild.id, caught=caught)
        self._invalidate_cache(message.guild.id)
        await self._refresh_trap_message(message.guild, updated)

        await self._send_alert(
            message.guild,
            updated,
            author,
            applied,
            content=content,
            attachment_count=attachment_count,
            channel_label=channel_mention,
        )


__all__ = ["HoneypotEvents"]
