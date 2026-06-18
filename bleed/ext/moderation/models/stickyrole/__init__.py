from __future__ import annotations
from dataclasses import dataclass


@dataclass
class StickyroleRecord:
    guild_id: int
    role_id: int
    user_id: int
