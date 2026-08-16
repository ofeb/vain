"""Feature-specific rate limiting helpers.
"""

from __future__ import annotations

import time
from typing import Dict, Hashable, Optional

from discord.ext.commands import CooldownMapping


NOTIFY_COOLDOWN = 10.0
FEATURE_APPLY_COOLDOWN = 2.0

_buckets: Dict[str, CooldownMapping] = {}
_notify_until: Dict[str, float] = {}
_apply_until: Dict[str, float] = {}


def ratelimiter(bucket: str, key: Hashable, rate: int, per: float) -> Optional[float]:
    """Bucket helper for feature-specific limits.

    Returns retry_after seconds when limited, else None.
    """
    if bucket not in _buckets:
        _buckets[bucket] = CooldownMapping.from_cooldown(rate, per, lambda k: k)
    mapping = _buckets[bucket]
    bkt = mapping.get_bucket(key)
    if bkt is None:
        return None
    return bkt.update_rate_limit()


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
