from __future__ import annotations
from dataclasses import dataclass


@dataclass
class WelcomeRecord:
    guild_id: int
    channel_id: int
    message: str
    dm: bool = False
    self_destruct: int | None = None
