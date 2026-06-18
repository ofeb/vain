from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TimezoneRecord:
    guild_id: int
    user_id: int
    timezone: str
