from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ThreadRecord:
    guild_id: int
    thread_id: int
    action: str
