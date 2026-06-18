from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AliasRecord:
    guild_id: int
    shortcut: str
    command: str
    invoke: str
