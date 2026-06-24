"""global command rate limiting with escalating cooldowns.

burst traffic triggers a wait that starts at 3s and grows by 3s for each
additional limit within a rolling minute window."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from discord.ext.commands import CooldownMapping

BURST_RATE = 2
BURST_PER = 4.0
BASE_COOLDOWN = 3.0
ESCALATION_STEP = 3.0
STRIKE_WINDOW = 60.0

_buckets: Dict[str, CooldownMapping] = {}


@dataclass
class _RateState:
    blocked_until: float = 0.0
    strikes: int = 0
    strike_window_start: float = 0.0
    command_times: list[float] = field(default_factory=list)


_states: Dict[Any, _RateState] = {}


def _state(key: Any) -> _RateState:
    if key not in _states:
        _states[key] = _RateState()
    return _states[key]


def _cooldown_for(strikes: int) -> float:
    return BASE_COOLDOWN + max(0, strikes - 1) * ESCALATION_STEP


def _register_strike(state: _RateState, now: float) -> float:
    if (
        state.strikes == 0
        or state.strike_window_start <= 0.0
        or (now - state.strike_window_start) > STRIKE_WINDOW
    ):
        state.strikes = 1
        state.strike_window_start = now
    else:
        state.strikes += 1
    cooldown = _cooldown_for(state.strikes)
    state.blocked_until = now + cooldown
    return cooldown


def global_ratelimit(key: Any) -> Optional[float]:
    """return retry_after seconds when limited, else None."""
    now = time.monotonic()
    state = _state(key)

    if now < state.blocked_until:
        return max(state.blocked_until - now, 0.01)

    if state.strikes > 0 and (now - state.strike_window_start) > STRIKE_WINDOW:
        state.strikes = 0
        state.strike_window_start = 0.0

    state.command_times = [t for t in state.command_times if now - t < BURST_PER]
    state.command_times.append(now)

    if len(state.command_times) > BURST_RATE:
        state.command_times.clear()
        return _register_strike(state, now)

    return None


def ratelimiter(bucket: str, key: Any, rate: int, per: float) -> Optional[float]:
    """legacy bucket helper for feature-specific limits."""
    if bucket not in _buckets:
        _buckets[bucket] = CooldownMapping.from_cooldown(rate, per, lambda k: k)
    bkt = _buckets[bucket].get_bucket(key)
    return bkt.update_rate_limit()
