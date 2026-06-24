"""per-user global command rate limiting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from discord.ext.commands import CooldownMapping

BASE_COOLDOWN = 3.0
BURST_RATE = 3
BURST_WINDOW = 1.0

_buckets: Dict[str, CooldownMapping] = {}


@dataclass
class _RateState:
    blocked_until: float = 0.0
    command_times: list[float] = field(default_factory=list)


_states: Dict[int, _RateState] = {}


def _state(user_id: int) -> _RateState:
    if user_id not in _states:
        _states[user_id] = _RateState()
    return _states[user_id]


def global_ratelimit(user_id: int) -> Optional[float]:
    """return retry_after seconds when limited, else None."""
    now = time.monotonic()
    state = _state(user_id)

    if now < state.blocked_until:
        return max(state.blocked_until - now, 0.01)

    state.command_times = [t for t in state.command_times if now - t < BURST_WINDOW]
    state.command_times.append(now)

    if len(state.command_times) > BURST_RATE:
        state.command_times.clear()
        state.blocked_until = now + BASE_COOLDOWN
        return BASE_COOLDOWN

    return None


def ratelimiter(bucket: str, key: Any, rate: int, per: float) -> Optional[float]:
    """legacy bucket helper for feature-specific limits."""
    if bucket not in _buckets:
        _buckets[bucket] = CooldownMapping.from_cooldown(rate, per, lambda k: k)
    bkt = _buckets[bucket].get_bucket(key)
    return bkt.update_rate_limit()
