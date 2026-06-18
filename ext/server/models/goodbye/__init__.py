from __future__ import annotations
from dataclasses import dataclass


@dataclass
class GoodbyeRecord:
    guild_id: int
    channel_id: int
    message: str
    self_destruct: int | None = None
