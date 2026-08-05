from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FakePermRecord:
    guild_id: int
    role_id: int
    permission: str
