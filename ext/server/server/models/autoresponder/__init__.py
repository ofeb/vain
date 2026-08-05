from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AutoresponderRecord:
    guild_id: int
    trigger: str
    response: str
    strict: bool = False
    ignore_case: bool = True
    role_id: int | None = None
    channel_id: int | None = None
