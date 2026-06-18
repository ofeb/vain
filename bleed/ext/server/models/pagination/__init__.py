from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class PaginationRecord:
    guild_id: int
    channel_id: int
    message_id: int
    current_page: int = 0
    embeds: List[str] = field(default_factory=list)
