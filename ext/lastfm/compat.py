"""Lightweight shims for optional deps used by the cure-main interface port."""

from __future__ import annotations

import functools
import time
from typing import Any, Callable


class _NullCache:
    """No-op stand-in for cashews.cache (avoids hard dependency)."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable:
        def deco(fn: Callable) -> Callable:
            return fn

        
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return deco

    def invalidate(self, *args: Any, **kwargs: Any) -> None:
        return None


cache = _NullCache()


class Redis:
    """Minimal async redis stub used by a few interface helpers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._store: dict[str, Any] = {}
        self._expiry: dict[str, float] = {}

    async def get(self, key: str) -> Any:
        exp = self._expiry.get(key)
        if exp is not None and time.time() > exp:
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return None
        return self._store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self._store[key] = value
        if ex:
            self._expiry[key] = time.time() + ex

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)
            self._expiry.pop(k, None)


def duration(seconds: float | int) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(max(seconds, 0), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
