from __future__ import annotations
from dataclasses import dataclass


@dataclass
class LockdownRecord:
    guild_id: int
    channel_id: int
    reason: str
