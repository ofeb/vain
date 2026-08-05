from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CustomizeRecord:
    guild_id: int
    nick: str | None = None
