from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TimeoutRecord:
    guild_id: int
    user_id: int
    duration: int
