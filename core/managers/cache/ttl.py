"""ttl cache decorator for async functions.
caches the return value and re-calls after expiry.
use ttl_cache on any async function"""

import asyncio, functools, time
from typing import Any, Callable, Optional


def ttl_cache(seconds: int = 60, key: Optional[str] = None):
    """cache async function result for given seconds.
    key can be a string template with {args}.
    returns stale value while refreshing if expired"""
    _cache: dict = {}

    def decorator(fn: Callable):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            cache_key = key.format(*args, **kwargs) if key else (fn.__name__, args, tuple(sorted(kwargs.items())))
            if cache_key in _cache:
                value, ts = _cache[cache_key]
                if time.time() - ts < seconds:
                    return value
            result = await fn(*args, **kwargs)
            _cache[cache_key] = (result, time.time())
            return result
        wrapper.cache_clear = lambda: _cache.clear()
        return wrapper
    return decorator
