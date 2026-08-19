from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import getLogger
from typing import Any

logger = getLogger("vain.afk.settings")


@dataclass
class AFKData:
    status: str
    timestamp: datetime


class Settings:
    """Global AFK state for one user (Redis hash `afk:{user_id}`)."""

    def __init__(self, redis: Any, user_id: int) -> None:
        self.redis = redis
        self.user_id = int(user_id)

    def _key(self) -> str:
        return f"afk:{self.user_id}"

    def __bool__(self) -> bool:
        return True

    @classmethod
    async def fetch(cls, redis: Any, user_id: int) -> AFKData | None:
        return await AFK(redis).get(user_id)

    async def upsert(self, status: str = "AFK", **kwargs: Any) -> None:
        await AFK(self.redis).set(self.user_id, status or "AFK")

    async def insert(self, status: str = "AFK", **kwargs: Any) -> None:
        await self.upsert(status=status)

    async def delete(self) -> bool:
        return await AFK(self.redis).remove(self.user_id)


class AFK:
    """Low-level Redis helpers used by Settings and events."""

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    def _key(self, user_id: int, guild_id: int | None = None) -> str:
        if guild_id is not None:
            return f"afk:{user_id}:{guild_id}"
        return f"afk:{user_id}"

    def _mentions_key(self, user_id: int, guild_id: int | None = None) -> str:
        if guild_id is not None:
            return f"afk:mentions:{user_id}:{guild_id}"
        return f"afk:mentions:{user_id}"

    async def set(self, user_id: int, status: str = "AFK", *, guild_id: int | None = None) -> None:
        mapping = {
            "status": (status or "AFK")[:200],
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        }
        key = self._key(user_id, guild_id)
        try:
            await self.redis.hset(key, mapping=mapping)
        except TypeError:
            for field, value in mapping.items():
                await self.redis.hset(key, field, value)
        expire = getattr(self.redis, "expire", None)
        if expire is not None:
            await expire(key, 7 * 86400)
        await self.clear_mentions(user_id, guild_id=guild_id)
        logger.debug("afk set user=%s guild=%s", user_id, guild_id)

    async def get(self, user_id: int, *, guild_id: int | None = None) -> AFKData | None:
        data = await self.redis.hgetall(self._key(user_id, guild_id))
        if not data:
            return None
        norm: dict[str, str] = {}
        items = data.items() if isinstance(data, dict) else data
        for k, v in items:
            kk = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
            norm[kk] = vv
        if not norm:
            return None
        try:
            ts = int(float(norm.get("timestamp") or 0))
        except Exception:
            ts = 0
        return AFKData(
            status=norm.get("status") or "AFK",
            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        )

    async def get_any(self, user_id: int, *, guild_id: int | None = None) -> AFKData | None:
        """Check guild-specific first, then fall back to global."""
        if guild_id is not None:
            data = await self.get(user_id, guild_id=guild_id)
            if data is not None:
                return data
        return await self.get(user_id)

    async def remove(self, user_id: int, *, guild_id: int | None = None) -> bool:
        try:
            result = await self.redis.delete(self._key(user_id, guild_id))
            return bool(result)
        except Exception:
            return False

    async def remove_any(self, user_id: int, *, guild_id: int | None = None) -> bool:
        """Remove guild-specific if it exists, otherwise remove global."""
        if guild_id is not None:
            removed = await self.remove(user_id, guild_id=guild_id)
            if removed:
                return True
        return await self.remove(user_id)

    async def exists(self, user_id: int, *, guild_id: int | None = None) -> bool:
        return bool(await self.redis.exists(self._key(user_id, guild_id)))

    async def exists_any(self, user_id: int, *, guild_id: int | None = None) -> bool:
        """Check guild-specific first, then global."""
        if guild_id is not None:
            if await self.exists(user_id, guild_id=guild_id):
                return True
        return await self.exists(user_id)

    async def clear_mentions(self, user_id: int, *, guild_id: int | None = None) -> None:
        with contextlib.suppress(Exception):
            await self.redis.delete(self._mentions_key(user_id, guild_id))

    async def add_mention(
        self,
        user_id: int,
        *,
        author_id: int,
        author_name: str,
        jump_url: str,
        channel_id: int,
        content: str,
        timestamp: float,
        guild_id: int | None = None,
    ) -> None:
        payload = json.dumps(
            {
                "author_id": author_id,
                "author_name": author_name,
                "jump_url": jump_url,
                "channel_id": channel_id,
                "guild_id": guild_id,
                "content": (content or "")[:200],
                "timestamp": timestamp,
            }
        )
        key = self._mentions_key(user_id, guild_id)
        try:
            await self.redis.rpush(key, payload)
            await self.redis.ltrim(key, -200, -1)
            await self.redis.expire(key, 7 * 86400)
        except Exception:
            pass

    async def get_mentions(self, user_id: int, *, guild_id: int | None = None) -> list[dict]:
        key = self._mentions_key(user_id, guild_id)
        try:
            rows = await self.redis.lrange(key, 0, -1)
        except Exception:
            return []
        out: list[dict] = []
        for row in rows or []:
            raw = row.decode() if isinstance(row, (bytes, bytearray)) else str(row)
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out


async def fetch(redis: Any, user_id: int, *, guild_id: int | None = None) -> AFKData | None:
    return await AFK(redis).get(user_id, guild_id=guild_id)


async def upsert(redis: Any, user_id: int, status: str = "AFK", *, guild_id: int | None = None) -> None:
    await AFK(redis).set(user_id, status, guild_id=guild_id)


async def insert(redis: Any, user_id: int, status: str = "AFK", *, guild_id: int | None = None) -> None:
    await upsert(redis, user_id, status, guild_id=guild_id)


__all__ = ["Settings", "AFK", "AFKData", "fetch", "upsert", "insert"]
