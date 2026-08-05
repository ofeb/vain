from __future__ import annotations
from dataclasses import dataclass


@dataclass
class IgnoreRecord:
    guild_id: int
    target_id: int
    target_type: str
