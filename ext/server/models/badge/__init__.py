from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BadgeRecord:
    guild_id: int
    user_id: int
    role_id: int
    color: int
