"""Per-user / per-feature rate limiting helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Hashable, Optional

from discord.ext.commands import CooldownMapping



BASE_COOLDOWN = 1.25
BURST_RATE = 4
BURST_WINDOW = 3.0
BURST_PENALTY = 10.0


SETUP_COOLDOWN = 10.0


NOTIFY_COOLDOWN = 10.0


FEATURE_APPLY_COOLDOWN = 2.0

_buckets: Dict[str, CooldownMapping] = {}


@dataclass
class _RateState:
    blocked_until: float = 0.0
    command_times: list[float] = field(default_factory=list)
    last_command_at: float = 0.0


_states: Dict[int, _RateState] = {}
_notify_until: Dict[str, float] = {}
_apply_until: Dict[str, float] = {}


def _state(user_id: int) -> _RateState:
    if user_id not in _states:
        _states[user_id] = _RateState()
    return _states[user_id]


def global_ratelimit(user_id: int) -> Optional[float]:
    """Return retry_after seconds when limited, else None.

    Rules:
      1. Hard lockout while ``blocked_until`` is in the future (burst abuse).
      2. Soft spacing — at most one command every ``BASE_COOLDOWN`` seconds.
      3. Burst — more than ``BURST_RATE`` commands inside ``BURST_WINDOW``
         triggers a ``BURST_PENALTY`` second lockout.
    """
    now = time.monotonic()
    state = _state(user_id)

    if now < state.blocked_until:
        return max(state.blocked_until - now, 0.01)

    
    since_last = now - state.last_command_at
    if state.last_command_at and since_last < BASE_COOLDOWN:
        return max(BASE_COOLDOWN - since_last, 0.01)

    state.command_times = [t for t in state.command_times if now - t < BURST_WINDOW]
    state.command_times.append(now)
    state.last_command_at = now

    if len(state.command_times) > BURST_RATE:
        state.command_times.clear()
        state.blocked_until = now + BURST_PENALTY
        return BURST_PENALTY

    return None


def ratelimiter(bucket: str, key: Hashable, rate: int, per: float) -> Optional[float]:
    """Legacy bucket helper for feature-specific limits.

    Returns retry_after seconds when limited, else None.
    """
    if bucket not in _buckets:
        _buckets[bucket] = CooldownMapping.from_cooldown(rate, per, lambda k: k)
    mapping = _buckets[bucket]
    bkt = mapping.get_bucket(key)
    if bkt is None:
        return None
    return bkt.update_rate_limit()


def setup_ratelimit(guild_id: int | None, user_id: int, command_key: str) -> Optional[float]:
    """Guild+user cooldown for setup / configuration commands (default 10s)."""
    key = (guild_id or 0, user_id, command_key)
    return ratelimiter("setup.commands", key, 1, SETUP_COOLDOWN)


def notify_ratelimited(key: str, *, per: float = NOTIFY_COOLDOWN) -> bool:
    """In-memory notify gate. True = skip sending (still cooling down).

    First call within a window is allowed and starts the cooldown; subsequent
    calls before ``per`` seconds elapse are blocked.
    """
    now = time.monotonic()
    until = _notify_until.get(key, 0.0)
    if now < until:
        return True
    _notify_until[key] = now + per
    
    if len(_notify_until) > 5000:
        stale = [k for k, exp in _notify_until.items() if exp <= now]
        for k in stale[:2000]:
            _notify_until.pop(k, None)
    return False


def apply_ratelimited(key: str, *, per: float = FEATURE_APPLY_COOLDOWN) -> bool:
    """True when vanity/tag role apply should be skipped (too soon)."""
    now = time.monotonic()
    until = _apply_until.get(key, 0.0)
    if now < until:
        return True
    _apply_until[key] = now + per
    if len(_apply_until) > 5000:
        stale = [k for k, exp in _apply_until.items() if exp <= now]
        for k in stale[:2000]:
            _apply_until.pop(k, None)
    return False



SETUP_COMMAND_MARKERS: frozenset[str] = frozenset(
    {
        "setup",
        "reset",
        "unset",
        "configure",
        "create",
        "delete",
        "disable",
        "enable",
        "install",
        "uninstall",
    }
)


def is_setup_command(qualified_name: str | None) -> bool:
    if not qualified_name:
        return False
    parts = qualified_name.lower().split()
    if not parts:
        return False
    
    leaf = parts[-1]
    if leaf in SETUP_COMMAND_MARKERS:
        return True
    
    if len(parts) >= 2 and parts[0] in {
        "honeypot",
        "voicemaster",
        "vanity",
        "tag",
        "autorole",
        "welcome",
        "goodbye",
        "starboard",
        "tickets",
        "ticket",
        "antiraid",
        "automod",
        "filter",
        "boosterrole",
        "bump",
        "counter",
        "counters",
        "log",
        "logging",
    } and leaf in SETUP_COMMAND_MARKERS | {
        "channel",
        "role",
        "roles",
        "message",
        "category",
        "panel",
    }:
        
        return leaf in SETUP_COMMAND_MARKERS
    return False
