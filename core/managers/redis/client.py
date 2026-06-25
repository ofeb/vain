"""redis client with ratelimit helpers.
extends redis.asyncio with custom locking and rate limiting.
use ratelimited to check burst limits"""

from __future__ import annotations
import asyncio, contextlib, itertools, time
from datetime import timedelta
from hashlib import sha1
from typing import Any, Dict, List, Optional, Union
import humanize, orjson, tuuid
from async_timeout import timeout as Timeout
from discord import Guild, Member, Message, TextChannel, User
from discord.ext.commands import Context
from loguru import logger as log
from redis.asyncio import Redis
from redis.asyncio.connection import BlockingConnectionPool
from redis.asyncio.lock import Lock
from redis.backoff import EqualJitterBackoff
from redis.exceptions import LockError, NoScriptError
from redis.retry import Retry
from xxhash import xxh3_64_hexdigest
from .lock import Semaphore

cachestring = "redis://127.0.0.1:6379"

_INC_SCRIPT = b"""
    local cur
    cur = tonumber(redis.call("incrby", KEYS[1], ARGV[2]))
    if cur == tonumber(ARGV[2]) then
        redis.call("expire", KEYS[1], ARGV[1])
    end
    return cur
"""
_INC_HASH = sha1(_INC_SCRIPT).hexdigest()

_MSG_SCRIPT = b"""
    local key = KEYS[1]
    local msg = ARGV[1]
    redis.call('RPUSH', key, msg)
    redis.call('LTRIM', key, -200, -1)
"""


def _fmt_seconds(seconds: Union[int, float]) -> str:
    """human readable time delta string"""
    return humanize.naturaldelta(timedelta(seconds=seconds), minimum_unit="microseconds")


class _JSONDecoder:
    def decode(self, obj):
        return orjson.loads(obj)


class _JSONEncoder:
    def encode(self, obj):
        return orjson.dumps(obj).decode("utf-8")


class BotLock(Lock):
    """redis lock that auto extends itself.
    keeps the lock alive while context manager is held.
    raises LockError if it **can't** acquire"""

    def __init__(self, redis: Redis, name, max_ttl: float = 30.0, extend_every: float = 0.5, **kw):
        self.extend_every = extend_every
        self._extend_task: Optional[asyncio.Task] = None
        self._held = False
        super().__init__(redis, name, max_ttl, **kw)

    async def _extender(self):
        while True:
            await asyncio.sleep(self.extend_every)
            await self.reacquire()

    async def __aenter__(self):
        if await self.acquire():
            self._held = True
            if self.extend_every:
                self._extend_task = asyncio.create_task(self._extender())
            return self
        raise LockError("**can't** acquire lock in time")

    async def __aexit__(self, *_):
        if self._extend_task:
            self._extend_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._extend_task
        await self.release()
        self._held = False


class BleedCache(Redis):
    """discord bot redis with helpers.
    wraps redis.asyncio with rate limiting and message storage.
    use from_url classmethod to connect"""

    def __init__(self, *a, **kw):
        self._locks: Dict[str, BotLock] = {}
        self._ns = tuuid.tuuid()
        self.rl_prefix = "rlb:"
        self.is_ratelimited = self.ratelimited
        self.rl_keys: dict = {}
        self.channels: list = []
        self.__sems: Dict[str, Semaphore] = {}
        super().__init__(*a, **kw)

    def json(self):
        return super().json(_JSONEncoder(), _JSONDecoder())

    @property
    def held_locks(self):
        return [{n: l} for n, l in self._locks.items() if l.locked()]

    def __repr__(self):
        return f"BleedCache ns={self._ns} pool={self.connection_pool!r}"

    async def jsonset(self, key, data: dict, **kw):
        return await self._json.set(key, ".", data, **kw)

    async def jsonget(self, key):
        return await self._json.get(key)

    async def jsondelete(self, key):
        return await self._json.delete(key)

    async def getstr(self, key) -> str:
        return (await self.get(key)).decode("utf-8")

    async def random(self, key: str) -> str | None:
        result = await self.srandmember(key)
        if isinstance(result, bytes):
            return result.decode("utf-8")
        if isinstance(result, list):
            if not result:
                return None
            item = result[0]
            return item.decode("utf-8") if isinstance(item, bytes) else item
        return result

    def get_semaphore(self, ident: str, count: int) -> Semaphore:
        """get or create semaphore for resource"""
        key = f"sem:{xxh3_64_hexdigest(ident)}"
        return Semaphore(self, count=count, namespace=key)

    async def subscribe(self, channel: str, dispatcher) -> bool:
        """subscribe to a pubsub channel"""
        if channel in self.channels:
            return False
        if not hasattr(self, "_pub"):
            self._pub = self._pubsub_()
        await self._pub.subscribe(channel)
        self.dispatcher = dispatcher
        self.channels.append(channel)
        return True

    async def read_messages(self):
        """loop reading pubsub messages"""
        if sub := getattr(self, "_pub", None):
            async def _reader(ps):
                while True:
                    try:
                        msg = await asyncio.wait_for(ps.get_message(ignore_subscribe_messages=True), timeout=10)
                        if msg:
                            await self.dispatcher.dispatch("message_received", msg)
                        else:
                            await asyncio.sleep(0.01)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        log.info(f"read_messages error: {e}")
            await _reader(sub)

    @classmethod
    async def from_url(cls, url=cachestring, attempts=100, conn_timeout=120, **kw):
        """connect to redis from url string"""
        retry = Retry(backoff=EqualJitterBackoff(3, 1), retries=attempts)
        inst = cls(
            connection_pool=BlockingConnectionPool.from_url(
                url, timeout=conn_timeout, max_connections=7000, retry=retry, **kw
            )
        )
        log.warning(f"redis connecting: {url}")
        ping_total = 0.0
        async with Timeout(9):
            for _ in range(5):
                t = time.time()
                await inst.ping()
                ping_total += time.time() - t
        avg = ping_total / 5
        log.success(f"redis ready avg ping: {_fmt_seconds(avg)}")
        return inst

    def _rl_key(self, ident: str) -> str:
        return f"{self.rl_prefix}{xxh3_64_hexdigest(ident)}"

    async def ratelimited(self, ident: str, limit: int, window: int = 60, inc: int = 1) -> bool:
        """true if ident has exceeded limit in window"""
        key = self._rl_key(ident)
        try:
            usage = await self.evalsha(_INC_HASH, 1, key, window, inc)
        except NoScriptError:
            usage = await self.eval(_INC_SCRIPT, 1, key, window, inc)
        self.rl_keys[ident] = key
        return int(usage) > limit

    async def add_message(self, message: Message) -> bool:
        """store message content in channel history"""
        key = xxh3_64_hexdigest(f"{message.guild.id}-{message.channel.id}-{message.author.id}")
        await self.eval(_MSG_SCRIPT, 1, key, message.clean_content)
        return True

    async def get_messages(self, ctx: Context) -> list:
        """get recent messages from ctx channel"""
        key = xxh3_64_hexdigest(
            f"{ctx.message.guild.id}-{ctx.message.channel.id}-{ctx.message.author.id}"
        )
        return await self.lrange(key, 0, -1)

    async def get_all_messages(
        self,
        guild: Union[Guild, int],
        user: Union[User, Member],
        channels: Optional[List[Any]] = None,
    ) -> list:
        """get all messages across guild channels for user"""
        async def _get(g, ch, u):
            if isinstance(g, Guild):
                key = xxh3_64_hexdigest(f"{g.id}-{ch.id}-{u.id}")
            else:
                key = xxh3_64_hexdigest(f"{g}-{ch}-{u.id}")
            return await self.lrange(key, 0, -1) or None

        if isinstance(guild, Guild):
            results = await asyncio.gather(*[_get(guild, ch, user) for ch in guild.text_channels])
        else:
            results = await asyncio.gather(*[_get(guild, ch, user) for ch in (channels or [])])
        return list(itertools.chain.from_iterable(r for r in results if r))
