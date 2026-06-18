from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RemindRecord:
    user_id: int
    reminder: str
    duration: int
