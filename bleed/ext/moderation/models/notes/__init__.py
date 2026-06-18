from __future__ import annotations
from dataclasses import dataclass


@dataclass
class NoteRecord:
    guild_id: int
    user_id: int
    note: str
