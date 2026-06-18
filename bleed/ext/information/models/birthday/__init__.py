from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BirthdayRecord:
    guild_id: int
    user_id: int
    birthday: str
