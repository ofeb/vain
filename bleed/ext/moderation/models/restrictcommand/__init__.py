from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RestrictcommandRecord:
    guild_id: int
    command: str
    role_id: int
