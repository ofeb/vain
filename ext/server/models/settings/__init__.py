from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TrackerConfig:
    guild_id: int
    tracker_type: str
    value: str
    channel_id: int | None = None
