from __future__ import annotations
from dataclasses import dataclass


@dataclass
class StickyRecord:
    guild_id: int
    channel_id: int
    message: str
    last_message_id: int | None = None
