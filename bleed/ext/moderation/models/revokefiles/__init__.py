from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RevokefilesRecord:
    guild_id: int
    channel_id: int
    enabled: bool
