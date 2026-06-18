from __future__ import annotations
from dataclasses import dataclass


@dataclass
class InvocationConfig:
    guild_id: int
    command: str
    dm_code: str | None = None
    message_code: str | None = None
