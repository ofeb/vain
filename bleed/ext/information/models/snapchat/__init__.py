from __future__ import annotations
from dataclasses import dataclass


@dataclass
class SnapchatRecord:
    discord_id: int
    snapchat_username: str
