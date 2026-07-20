from __future__ import annotations

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

    def _key(self, user_id: int) -> str:
        return f"afk:{user_id}"

    async def set(self, user_id: int, status: str = "AFK") -> None:
        mapping = {
            "status": (status or "AFK")[:200],
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        }
        key = self._key(user_id)
        await self.redis.hset(key, mapping=mapping)
        await self.redis.expire(key, 7 * 86400)
        logger.debug("afk set user=%s", user_id)

    async def get(self, user_id: int) -> AFKData | None:
        data = await self.redis.hgetall(self._key(user_id))
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
        except ValueError:
            ts = 0
        return AFKData(
            status=norm.get("status") or "AFK",
            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        )

    async def remove(self, user_id: int) -> bool:
        return bool(await self.redis.delete(self._key(user_id)))

    async def exists(self, user_id: int) -> bool:
        return bool(await self.redis.exists(self._key(user_id)))


async def fetch(redis: Any, user_id: int) -> AFKData | None:
    return await AFK(redis).get(user_id)


async def upsert(redis: Any, user_id: int, status: str = "AFK") -> None:
    await AFK(redis).set(user_id, status)


async def insert(redis: Any, user_id: int, status: str = "AFK") -> None:
    await upsert(redis, user_id, status)


__all__ = ["Settings", "AFK", "AFKData", "fetch", "upsert", "insert"]
