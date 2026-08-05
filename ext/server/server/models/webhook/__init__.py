from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class WebhookRecord:
    guild_id: int
    channel_id: int
    id: str
    name: str
    url: str
    created_by: int
    message_ids: List[int] = field(default_factory=list)
