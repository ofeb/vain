"""async task guard and scheduler.
tracks spawned tasks and cancels them by identity key.
use spawn to track coroutines safely"""

from __future__ import annotations

from asyncio import CancelledError, Future, Lock, Task, ensure_future, gather
from contextlib import suppress
from collections.abc import Coroutine
from typing import Union

try:
    from asyncio import timeout
except ImportError:
    from async_timeout import timeout

from loguru import logger


class TaskMap:
    """named collection of tasks with a lock"""

    def __init__(self, name: str) -> None:
        self.lock = Lock()
        self.name = name
        self.tasks: dict = {}

    @classmethod
    def create(cls, name: str) -> TaskMap:
        return cls(name)


class Guard:
    """task lifecycle manager.
    spawns coroutines with identity keys so they can be cancelled later.
    tracks failures and cancellations"""

    def __init__(self) -> None:
        self.control: Lock = Lock()
        self.failed: int = 0
        self.cancelled: int = 0
        self._tasks: dict[str, set[Future]] = {}

    def __str__(self) -> str:
        return f"<Guard failed={self.failed} cancelled={self.cancelled}>"

    def _on_done(self, ident: str, task: Future) -> None:
        bucket = self._tasks.get(ident)
        if bucket is not None:
            bucket.discard(task)
            if not bucket:
                self._tasks.pop(ident, None)

        try:
            if task.cancelled():
                self.cancelled += 1
                return
            task.result()
        except CancelledError:
            self.cancelled += 1
        except Exception:
            self.failed += 1
            logger.exception("guarded task {} failed", ident)

    async def spawn(self, coro: Union[Coroutine, Future, Task], ident: str) -> Union[Future, Task]:
        """spawn coroutine tracked under ident key"""
        ident = str(ident)
        task = ensure_future(coro)
        async with self.control:
            self._tasks.setdefault(ident, set()).add(task)
        task.add_done_callback(lambda done, ident=ident: self._on_done(ident, done))
        return task

    async def shutdown(self, ident: str) -> int:
        """cancel all tasks matching ident prefix"""
        ident = str(ident)
        async with self.control:
            tasks = [
                task
                for key, bucket in list(self._tasks.items())
                if key.startswith(ident)
                for task in bucket
            ]
            for key in [key for key in self._tasks if key.startswith(ident)]:
                self._tasks.pop(key, None)

        for task in tasks:
            task.cancel()

        if tasks:
            with suppress(Exception):
                async with timeout(10):
                    await gather(*tasks, return_exceptions=True)
        return len(tasks)
