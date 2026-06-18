"""redis semaphore for concurrency control.
limits concurrent access to a shared resource.
use as async context manager"""

import time
from typing import Any, Callable, List, Optional
from redis import Redis, StrictRedis


class NotAvailable(Exception):
    """no semaphore slots left"""
    pass


class Semaphore:
    """counting semaphore backed by redis.
    tracks how many callers hold a token at once.
    stale locks get cleaned up automatically if timeout set"""

    EXISTS = "ok"

    def __init__(
        self,
        client: Redis,
        count: int,
        namespace: str = "SEM",
        stale_timeout: Optional[int] = None,
        blocking: bool = False,
    ) -> None:
        if count < 1:
            raise ValueError("count must be at least 1")
        self.client = client or StrictRedis()
        self.count = count
        self.namespace = namespace
        self.stale_timeout = stale_timeout
        self.use_local_time = False
        self.blocking = blocking
        self._tokens: List[bytes] = []

    def _key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    def _get_key(self, attr: str, suffix: str) -> str:
        if not hasattr(self, attr):
            setattr(self, attr, self._key(suffix))
        return getattr(self, attr)

    @property
    def exists_key(self) -> str:
        return self._get_key("_exists_key", "EXISTS")

    @property
    def avail_key(self) -> str:
        return self._get_key("_avail_key", "AVAILABLE")

    @property
    def grabbed_key(self) -> str:
        return self._get_key("_grabbed_key", "GRABBED")

    @property
    def release_key(self) -> str:
        return self._get_key("_release_key", "RELEASE_LOCKS")

    async def _init(self) -> None:
        await self.client.expire(self.exists_key, 10)
        async with self.client.pipeline() as pipe:
            pipe.multi()
            await pipe.delete(self.grabbed_key, self.avail_key)
            await pipe.rpush(self.avail_key, *range(self.count))
            await pipe.execute()
        await self.client.persist(self.exists_key)

    async def _ensure_init(self) -> None:
        old = await self.client.getset(self.exists_key, self.EXISTS)
        if not old:
            await self._init()

    async def count_available(self) -> int:
        """how many slots are free right now"""
        return await self.client.llen(self.avail_key)

    async def acquire(self, timeout: int = 0, target: Optional[Callable] = None) -> bytes:
        """grab a semaphore slot"""
        await self._ensure_init()
        if self.stale_timeout is not None:
            await self._clean_stale()
        if self.blocking:
            pair = await self.client.blpop(self.avail_key, timeout)
            if pair is None:
                raise NotAvailable
            token = pair[1]
        else:
            token = await self.client.lpop(self.avail_key)
            if token is None:
                raise NotAvailable
        self._tokens.append(token)
        await self.client.hset(self.grabbed_key, token, await self._now())
        if target is not None:
            try:
                target(token)
            finally:
                await self._signal(token)
        return token

    async def _clean_stale(self, expires: int = 10) -> None:
        token = await self.client.getset(self.release_key, self.EXISTS)
        if token:
            return
        await self.client.expire(self.release_key, expires)
        try:
            for tok, grabbed_at in await self.client.hgetall(self.grabbed_key):
                if float(grabbed_at) + (self.stale_timeout or 0) < await self._now():
                    await self._signal(tok)
        finally:
            await self.client.delete(self.release_key)

    async def _is_held(self, token: bytes) -> bool:
        return await self.client.hexists(self.grabbed_key, token)

    async def has_lock(self) -> bool:
        """check if we hold any token"""
        for t in self._tokens:
            if await self._is_held(t):
                return True
        return False

    async def release(self) -> None:
        """give back a token"""
        if not await self.has_lock():
            return
        await self._signal(self._tokens.pop())

    async def reset(self) -> None:
        """reset all slots back to full"""
        await self._init()

    async def _signal(self, token: bytes) -> None:
        async with self.client.pipeline() as pipe:
            pipe.multi()
            await pipe.hdel(self.grabbed_key, token)
            await pipe.lpush(self.avail_key, token)
            await pipe.execute()

    async def _now(self) -> float:
        if self.use_local_time:
            return time.time()
        return float(".".join(map(str, await self.client.time())))

    async def __aenter__(self) -> "Semaphore":
        await self.acquire()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.release()
