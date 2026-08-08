"""file-backed redis-compatible store (.redis extension).

persists key/value data to disk when redis.enabled is false in values.py.
implements the subset of redis commands used by vain-bot."""

from __future__ import annotations

import asyncio
import itertools
import random
import time
from datetime import timedelta
from hashlib import sha1
from pathlib import Path
from typing import Any, List, Optional, Union

import humanize
import orjson
from discord import Guild, Member, Message, User
from discord.ext.commands import Context
from loguru import logger as log
from xxhash import xxh3_64_hexdigest

from core.managers.filetypes import CACHE_REDIS_FILE


def _resolve_path(path: str | Path | None = None) -> Path:
    if path is not None and Path(path).name != "cache.redis":
        raise ValueError("redis storage file must be named cache.redis")
    CACHE_REDIS_FILE.parent.mkdir(parents=True, exist_ok=True)
    return CACHE_REDIS_FILE


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
    return humanize.naturaldelta(timedelta(seconds=seconds), minimum_unit="microseconds")


class FileVainCache:
    """redis-compatible cache backed by a single .redis json file."""

    def __init__(self, path: str | Path) -> None:
        self.path = _resolve_path(path)
        self._lock = asyncio.Lock()
        self._keys: dict[str, dict[str, Any]] = {}
        self.rl_prefix = "rlb:"
        self.is_ratelimited = self.ratelimited
        self.rl_keys: dict = {}
        self.channels: list = []

    def __repr__(self) -> str:
        return f"FileVainCache(path={self.path!s}, keys={len(self._keys)})"

    @classmethod
    async def open(cls, path: str | Path | None = None) -> FileVainCache:
        inst = cls(_resolve_path(path))
        await inst._load()
        log.info("file redis ready at {}", inst.path)
        return inst

    async def _load(self) -> None:
        if not self.path.exists():
            self._keys = {}
            await self._save()
            return
        try:
            raw = self.path.read_bytes()
            data = orjson.loads(raw) if raw else {}
            self._keys = data.get("keys", {}) if isinstance(data, dict) else {}
        except Exception as e:
            log.warning("failed to load {}: {}, starting empty", self.path, e)
            self._keys = {}
            await self._save()

    async def _save(self) -> None:
        payload = orjson.dumps({"keys": self._keys})
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(self.path)

    def _entry(self, key: str) -> dict[str, Any] | None:
        entry = self._keys.get(key)
        if entry is None:
            return None
        exp = entry.get("exp")
        if exp is not None and time.time() >= float(exp):
            self._keys.pop(key, None)
            return None
        return entry

    def _ensure(self, key: str, kind: str, value: Any) -> dict[str, Any]:
        entry = self._entry(key)
        if entry is None:
            entry = {"kind": kind, "value": value, "exp": None}
            self._keys[key] = entry
            return entry
        if entry["kind"] != kind:
            entry = {"kind": kind, "value": value, "exp": None}
            self._keys[key] = entry
        return entry

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        async with self._lock:
            await self._save()

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            removed = 0
            for key in keys:
                if self._keys.pop(key, None) is not None:
                    removed += 1
            if removed:
                await self._save()
            return removed

    async def exists(self, key: str) -> int:
        return 1 if self._entry(key) is not None else 0

    async def expire(self, key: str, seconds: int) -> bool:
        async with self._lock:
            entry = self._entry(key)
            if entry is None:
                return False
            entry["exp"] = time.time() + int(seconds)
            await self._save()
            return True

    async def get(self, key: str) -> Any:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "string":
            return None
        return entry.get("value")

    async def set(self, key: str, value: Any, ex: int | None = None, **_: Any) -> bool:
        async with self._lock:
            entry = {"kind": "string", "value": value, "exp": None}
            if ex is not None:
                entry["exp"] = time.time() + int(ex)
            self._keys[key] = entry
            await self._save()
            return True

    async def incrby(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            entry = self._entry(key)
            if entry is None or entry.get("kind") != "string":
                current = 0
            else:
                current = int(entry.get("value") or 0)
            value = current + int(amount)
            new_entry = {"kind": "string", "value": value, "exp": entry.get("exp") if entry else None}
            self._keys[key] = new_entry
            await self._save()
            return value

    async def getstr(self, key: str) -> str:
        value = await self.get(key)
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def sadd(self, key: str, *values: Any) -> int:
        async with self._lock:
            entry = self._ensure(key, "set", [])
            current = set(entry["value"])
            before = len(current)
            for value in values:
                current.add(self._normalize_member(value))
            entry["value"] = sorted(current)
            added = len(current) - before
            await self._save()
            return added

    @staticmethod
    def _normalize_member(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def sismember(self, key: str, member: Any) -> int:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "set":
            return 0
        return 1 if self._normalize_member(member) in entry["value"] else 0

    async def smembers(self, key: str) -> list[str]:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "set":
            return []
        return list(entry["value"])

    async def srandmember(self, key: str, count: int = 1) -> str | list[str] | None:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "set" or not entry["value"]:
            return None
        if count == 1:
            return random.choice(entry["value"])
        return random.sample(entry["value"], min(count, len(entry["value"])))

    async def random(self, key: str) -> str | None:
        result = await self.srandmember(key)
        if isinstance(result, list):
            return result[0] if result else None
        return result

    async def rpush(self, key: str, *values: Any) -> int:
        async with self._lock:
            entry = self._ensure(key, "list", [])
            for value in values:
                entry["value"].append(self._normalize_member(value))
            await self._save()
            return len(entry["value"])

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "list":
            return []
        values = entry["value"]
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        async with self._lock:
            entry = self._entry(key)
            if entry is None or entry.get("kind") != "list":
                return False
            values = entry["value"]
            if end == -1:
                end = len(values) - 1
            entry["value"] = values[start : end + 1]
            await self._save()
            return True

    async def llen(self, key: str) -> int:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "list":
            return 0
        return len(entry["value"])

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: Any = None,
        mapping: dict | None = None,
    ) -> int:
        """Redis-compatible hset: ``hset(key, field, value)`` or ``hset(key, mapping={...})``."""
        pairs: dict[str, Any] = {}
        if mapping is not None:
            pairs.update({str(k): v for k, v in mapping.items()})
        if field is not None:
            pairs[str(field)] = value
        if not pairs:
            return 0
        async with self._lock:
            entry = self._ensure(key, "hash", {})
            created = 0
            for f, v in pairs.items():
                if f not in entry["value"]:
                    created += 1
                entry["value"][f] = self._normalize_member(v)
            await self._save()
            return created

    async def hget(self, key: str, field: str) -> str | None:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "hash":
            return None
        return entry["value"].get(str(field))

    async def hgetall(self, key: str) -> list[tuple[bytes, bytes]]:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "hash":
            return []
        pairs: list[tuple[bytes, bytes]] = []
        for field, value in entry["value"].items():
            pairs.append((str(field).encode(), str(value).encode()))
        return pairs

    async def hdel(self, key: str, field: str) -> int:
        async with self._lock:
            entry = self._entry(key)
            if entry is None or entry.get("kind") != "hash":
                return 0
            removed = 1 if entry["value"].pop(str(field), None) is not None else 0
            if removed:
                await self._save()
            return removed

    async def hexists(self, key: str, field: str) -> bool:
        entry = self._entry(key)
        if entry is None or entry.get("kind") != "hash":
            return False
        return str(field) in entry["value"]

    async def eval(self, script: bytes, numkeys: int, *args: Any) -> Any:
        if script == _INC_SCRIPT and numkeys == 1:
            key, window, inc = args[0], int(args[1]), int(args[2])
            usage = await self.incrby(key, inc)
            if usage == inc:
                await self.expire(key, window)
            return usage
        if script == _MSG_SCRIPT and numkeys == 1:
            key, msg = args[0], args[1]
            await self.rpush(key, msg)
            await self.ltrim(key, -200, -1)
            return True
        raise NotImplementedError("unsupported lua script for file redis")

    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> Any:
        if sha == _INC_HASH:
            return await self.eval(_INC_SCRIPT, numkeys, *args)
        raise NotImplementedError(f"unsupported script hash {sha}")

    def _rl_key(self, ident: str) -> str:
        return f"{self.rl_prefix}{xxh3_64_hexdigest(ident)}"

    async def ratelimited(self, ident: str, limit: int, window: int = 60, inc: int = 1) -> bool:
        key = self._rl_key(ident)
        usage = await self.evalsha(_INC_HASH, 1, key, window, inc)
        self.rl_keys[ident] = key
        return int(usage) > limit

    async def add_message(self, message: Message) -> bool:
        key = xxh3_64_hexdigest(f"{message.guild.id}-{message.channel.id}-{message.author.id}")
        await self.eval(_MSG_SCRIPT, 1, key, message.clean_content)
        return True

    async def get_messages(self, ctx: Context) -> list:
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

    @classmethod
    async def from_url(cls, *_: Any, **__: Any) -> FileVainCache:
        """compat alias - file store ignores redis urls."""
        return await cls.open(CACHE_REDIS_FILE)
