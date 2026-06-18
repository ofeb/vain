"""async task guard and scheduler.
tracks spawned tasks and cancels them by identity key.
use spawn to track coroutines safely"""

from __future__ import annotations
from asyncio import (
    AbstractEventLoop,
    CancelledError,
    Future,
    LifoQueue,
    Lock,
    Task,
    ensure_future,
    gather,
    get_running_loop,
)
from contextlib import suppress
from typing import Dict, Union
from collections.abc import Coroutine

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
        self.queue: LifoQueue = LifoQueue()
        self.control: Lock = Lock()
        self.failed: int = 0
        self.cancelled: int = 0
        self._locks: Dict[str, Lock] = {}
        self.loop: AbstractEventLoop = get_running_loop()

    def __str__(self) -> str:
        return f"<Guard failed={self.failed} cancelled={self.cancelled}>"

    async def _recycler(self) -> None:
        while True:
            task: Future = await self.queue.get()
            if not task.cancelled():
                task.exception()

    async def _get_lock(self, name: str) -> Lock:
        async with self.control:
            if name not in self._locks:
                self._locks[name] = Lock()
            return self._locks[name]

    def _on_done(self, task: Future) -> None:
        try:
            if not task.cancelled():
                with logger.catch(exclude=CancelledError, onerror=lambda _: setattr(self, "failed", self.failed + 1)):
                    task.result()
            else:
                self.cancelled += 1
        finally:
            key = getattr(task, "key", None)
            if key:
                self.loop.call_soon(lambda: self._locks.pop(key, None))

    async def spawn(self, coro: Union[Coroutine, Future, Task], ident: str) -> Union[Future, Task]:
        """spawn coroutine tracked under ident key"""
        ident = str(ident)
        async with await self._get_lock(ident):
            task = ensure_future(coro, loop=self.loop)
            task.key = f"{ident}-{id(coro)}"
            task.add_done_callback(self._on_done)
            return task

    async def shutdown(self, ident: str) -> int:
        """cancel all tasks matching ident prefix"""
        ident = str(ident)
        async with await self._get_lock(ident):
            to_cancel = [
                t.cancel()
                for key, t in self._locks.items()
                if key.startswith(ident)
            ]
            if to_cancel:
                async with timeout(10):
                    await gather(*to_cancel, return_exceptions=True)
            return len(to_cancel)
