from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class StickyRecord:
    guild_id: int
    channel_id: int
    message: str
    last_message_id: int | None = None
    message_limit: int = 5
    interval_seconds: int = 300
    message_count: int = 0
    last_sent: datetime | None = None
