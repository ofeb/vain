"""custom event dispatcher for internal events.
lets cogs emit and listen to bot specific events.
use bot.dispatch or register_listener"""

from discord.ext import commands
from typing import Any, Callable, Dict, List


class Dispatcher:
    """simple event bus for internal events.
    register handlers with on and emit with dispatch.
    handlers are called with any args passed"""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}

    def on(self, event: str, handler: Callable) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def dispatch(self, event: str, *args: Any, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            await handler(*args, **kwargs)

    def remove(self, event: str, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event].discard(handler)
