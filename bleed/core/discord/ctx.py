"""custom bot context with helpers.
extends commands.Context with send shortcuts and cache.
use ctx.success ctx.fail ctx.warn for quick replies"""

from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional, Union
import discord
from discord.ext import commands
from discord.ext.commands import CommandError
from discord.ui import View
from loguru import logger
from core.managers.values import emojis


class Cache:
    """lightweight in memory key value cache.
    supports ttl expiry and set operations.
    stores per bot instance"""

    def __init__(self, bot=None) -> None:
        self.bot = bot
        self._data: dict = {}
        self._futures: dict = {}

    async def _expire(self, key: str, ttl: int) -> None:
        await asyncio.sleep(ttl)
        self._data.pop(key, None)

    async def set(self, key: Any, value: Any, ttl: Optional[int] = None) -> int:
        self._data[key] = value
        if ttl is not None:
            if key in self._futures:
                self._futures[key].cancel()
            self._futures[key] = asyncio.ensure_future(self._expire(key, ttl))
        return 1

    async def get(self, key: Any) -> Any:
        return self._data.get(key)

    async def delete(self, key: Any) -> int:
        self._data.pop(key, None)
        return 1

    async def sadd(self, key: Any, *values: Any) -> int:
        if key not in self._data:
            self._data[key] = set()
        assert isinstance(self._data[key], set), "key is not a set"
        added = {v for v in values if v not in self._data[key]}
        self._data[key].update(added)
        return len(added)

    async def smembers(self, key: Any):
        return self._data.get(key, set())

    async def ratelimited(self, key: str, limit: int, window: int) -> Optional[float]:
        """simple in memory rate limit check"""
        import time
        now = time.time()
        bucket = self._data.setdefault(f"rl:{key}", [])
        bucket[:] = [t for t in bucket if now - t < window]
        if len(bucket) >= limit:
            return window - (now - bucket[0])
        bucket.append(now)
        return None


class Context(commands.Context):
    """extended bot context with reply helpers.
    adds success fail warn and embed shortcuts.
    also tracks flags for parsed command args"""

    flags: dict = {}

    @property
    def color(self) -> int:
        return self.bot.color

    async def success(self, message: str, **kw) -> discord.Message:
        """send a success reply with tick emoji"""
        emoji = emojis.approve
        return await self.reply(f"{emoji} {self.author.mention}: {message}", **kw)

    async def fail(self, message: str, **kw) -> discord.Message:
        """send a failure reply with x emoji"""
        emoji = emojis.deny
        return await self.reply(f"{emoji} {self.author.mention}: {message}", **kw)

    async def warn(self, message: str, **kw) -> discord.Message:
        """send a warning reply"""
        emoji = emojis.warn
        return await self.reply(f"{emoji} {self.author.mention}: {message}", **kw)

    async def send_embed(self, code: str, **kw) -> discord.Message:
        """parse embed script and send it"""
        return await self.bot.send_embed(self, code, **kw)

    async def paginate(self, entries: list, **kw) -> None:
        """send paginated list of entries"""
        from core.tools.pages import Paginator
        p = Paginator(self, entries, **kw)
        await p.start()
