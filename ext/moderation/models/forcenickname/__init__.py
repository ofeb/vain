from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ForcenicknameRecord:
    guild_id: int
    user_id: int
    nickname: str
