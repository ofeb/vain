from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RobloxRecord:
    discord_id: int
    roblox_id: int
    username: str
