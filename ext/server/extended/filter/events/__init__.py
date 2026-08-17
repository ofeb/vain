from __future__ import annotations

import contextlib
import logging
import re
import time
from collections import defaultdict

import discord

from core.discord.package import Package

log = logging.getLogger("vain.server.extended.filter")

LINK_REGEX = re.compile(r"https?://[^\s]+")
INVITE_REGEX = re.compile(
    r"(?:discord(?:app)?\.com/invite/|discord\.gg/)([a-zA-Z0-9-]+)"
)
CUSTOM_EMOJI_REGEX = re.compile(r"<a?:\w+:\d+>")
UNICODE_EMOJI_REGEX = re.compile(
    "[\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa70-\U0001faff"
    "\U0001f1e6-\U0001f1ff"
    "\U00002600-\U000027bf"
    "\U0000fe00-\U0000fe0f"
    "\U00002b00-\U00002bff"
    "\U0001f000-\U0001f0ff]"
)
MUSIC_EXTENSIONS = {
    "mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus", "aiff", "aif",
}
CACHE_TTL = 30.0
SPAM_WINDOW = 5.0


class FilterEvents(Package):
    """enforce the configured chat filters (caps, spoilers, music, emoji, regex, spam)"""

    _cache: dict[tuple[int, str], tuple[float, object]] = {}
    _regex_cache: dict[int, tuple[float, list]] = {}
    _spam: dict[tuple[int, int], list[float]] = defaultdict(list)

    async def _row(self, guild_id: int, table: str):
        key = (guild_id, table)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            return cached[1]
        row = await self.db.fetchrow(
            f"SELECT * FROM moderation.{table} WHERE guild_id = $1", guild_id
        )
        self._cache[key] = (time.monotonic(), row)
        return row

    def _invalidate(self, guild_id: int, table: str):
        self._cache.pop((guild_id, table), None)

    async def _regex_rows(self, guild_id: int) -> list:
        cached = self._regex_cache.get(guild_id)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            return cached[1]
        rows = await self.db.fetch(
            "SELECT regex, action, exempt_roles FROM moderation.regex WHERE guild_id = $1",
            guild_id,
        )
        self._regex_cache[guild_id] = (time.monotonic(), rows)
        return rows

    def _is_exempt(self, message: discord.Message, row) -> bool:
        if message.author.bot or message.author.id == message.guild.owner_id:
            return True
        exempt = set(row.get("exempt_roles") or [])
        if not exempt:
            return False
        return any(r.id in exempt for r in getattr(message.author, "roles", ()))

    async def _punish(self, message: discord.Message, action: str, reason: str) -> None:
        action = (action or "delete").lower()
        if action == "kick":
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await message.author.kick(reason=reason)
        elif action == "ban":
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await message.author.ban(reason=reason, delete_message_seconds=0)
        else:
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await message.delete()

    

    async def _check_caps(self, message: discord.Message) -> bool:
        row = await self._row(message.guild.id, "caps")
        if not row or self._is_exempt(message, row):
            return False
        threshold = row.get("threshold") or 70
        letters = [c for c in message.content if c.isalpha()]
        if not letters:
            return False
        upper = sum(1 for c in letters if c.isupper())
        if upper / len(letters) * 100 < threshold:
            return False
        await self._punish(message, row.get("action"), f"caps filter ({threshold}%)")
        return True

    async def _check_spoilers(self, message: discord.Message) -> bool:
        row = await self._row(message.guild.id, "spoilers")
        if not row or self._is_exempt(message, row):
            return False
        threshold = row.get("threshold") or 5
        if message.content.count("||") // 2 < threshold:
            return False
        await self._punish(message, row.get("action"), "spoiler filter")
        return True

    async def _check_music(self, message: discord.Message) -> bool:
        row = await self._row(message.guild.id, "music")
        if not row or self._is_exempt(message, row):
            return False
        for att in message.attachments:
            ext = (att.filename.rsplit(".", 1)[-1] if "." in att.filename else "").lower()
            if ext in MUSIC_EXTENSIONS or (att.content_type or "").startswith("audio/"):
                await self._punish(message, row.get("action"), "music file filter")
                return True
        return False

    async def _check_emoji(self, message: discord.Message) -> bool:
        row = await self._row(message.guild.id, "emoji")
        if not row or self._is_exempt(message, row):
            return False
        threshold = row.get("threshold") or 5
        count = (
            len(CUSTOM_EMOJI_REGEX.findall(message.content))
            + len(UNICODE_EMOJI_REGEX.findall(message.content))
        )
        if count < threshold:
            return False
        await self._punish(message, row.get("action"), "emoji filter")
        return True

    async def _check_regex(self, message: discord.Message) -> bool:
        rows = await self._regex_rows(message.guild.id)
        if not rows:
            return False
        for row in rows:
            exempt = set(row.get("exempt_roles") or [])
            if exempt and any(r.id in exempt for r in getattr(message.author, "roles", ())):
                continue
            try:
                if re.search(row["regex"], message.content):
                    await self._punish(message, row.get("action"), "regex filter")
                    return True
            except re.error:
                continue
        return False

    async def _check_spam(self, message: discord.Message) -> bool:
        row = await self._row(message.guild.id, "spam")
        if not row or self._is_exempt(message, row):
            return False
        threshold = row.get("threshold") or 5
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        window = [t for t in self._spam[key] if now - t < SPAM_WINDOW]
        window.append(now)
        self._spam[key] = window
        if len(self._spam) > 10_000:
            self._spam.clear()
        if len(window) < threshold:
            return False
        self._spam[key] = []
        await self._punish(message, row.get("action"), "spam filter")
        return True

    async def _check_content(self, message: discord.Message) -> bool:
        for check in (
            self._check_caps,
            self._check_spoilers,
            self._check_music,
            self._check_emoji,
            self._check_regex,
        ):
            if await check(message):
                return True
        return False

    @Package.listener("on_message")
    async def on_filter_message(self, message: discord.Message) -> None:
        if (
            message.author.bot
            or not message.guild
            or not isinstance(message.channel, (discord.TextChannel, discord.Thread))
        ):
            return
        if not await self._check_content(message):
            await self._check_spam(message)

    @Package.listener("on_message_edit")
    async def on_filter_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.content == after.content:
            return
        if (
            after.author.bot
            or not after.guild
            or not isinstance(after.channel, (discord.TextChannel, discord.Thread))
        ):
            return
        await self._check_content(after)
