from __future__ import annotations
from dataclasses import dataclass


@dataclass
class NukeRecord:
    guild_id: int
    channel_id: int
    interval: int
    message: str
