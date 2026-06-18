"""generic async in memory key value store.
supports optional ttl expiry per key.
use Store as a shared cache across cogs"""

import asyncio
from typing import Any, Optional


class Store:
    """simple async dict with expiring keys"""

    def __init__(self):
        self._data: dict = {}
        self._tasks: dict = {}

    async def set(self, key: Any, value: Any, ttl: Optional[int] = None) -> None:
        """store a value optionally expiring after ttl seconds"""
        self._data[key] = value
        if key in self._tasks:
            self._tasks[key].cancel()
        if ttl:
            self._tasks[key] = asyncio.create_task(self._expire(key, ttl))

    async def _expire(self, key: Any, ttl: int) -> None:
        await asyncio.sleep(ttl)
        self._data.pop(key, None)
        self._tasks.pop(key, None)

    async def get(self, key: Any, default: Any = None) -> Any:
        """get value or default if missing"""
        return self._data.get(key, default)

    async def delete(self, key: Any) -> bool:
        """remove a key and cancel its expiry task"""
        if t := self._tasks.pop(key, None):
            t.cancel()
        return bool(self._data.pop(key, None))

    async def exists(self, key: Any) -> bool:
        return key in self._data

    async def clear(self) -> int:
        n = len(self._data)
        for t in self._tasks.values():
            t.cancel()
        self._data.clear()
        self._tasks.clear()
        return n

    def __len__(self) -> int:
        return len(self._data)
