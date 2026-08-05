from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PurgeRecord:
    guild_id: int
    channel_id: int
    amount: int
