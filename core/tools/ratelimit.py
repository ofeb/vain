"""in process cooldown bucket manager.
maps bucket names to CooldownMapping instances.
use ratelimiter function to check limits"""

from typing import Any, Dict, Optional
from discord.ext.commands import CooldownMapping

_buckets: Dict[str, CooldownMapping] = {}


def ratelimiter(bucket: str, key: Any, rate: int, per: float) -> Optional[float]:
    """return retry_after seconds or None if not limited.
    bucket is a string key for the mapping group.
    key is what gets tracked eg user id or guild id"""
    if bucket not in _buckets:
        _buckets[bucket] = CooldownMapping.from_cooldown(rate, per, lambda k: k)
    bkt = _buckets[bucket].get_bucket(key)
    return bkt.update_rate_limit()
