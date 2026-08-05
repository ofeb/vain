from __future__ import annotations
from dataclasses import dataclass


@dataclass
class SlowmodeRecord:
    guild_id: int
    channel_id: int
    delay: int
