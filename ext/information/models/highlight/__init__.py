from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HighlightRecord:
    guild_id: int
    user_id: int
    keyword: str
