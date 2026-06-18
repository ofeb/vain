from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HistoryRecord:
    guild_id: int
    user_id: int
    action: str
    reason: str
