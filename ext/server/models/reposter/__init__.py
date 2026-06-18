from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ReposterRecord:
    guild_id: int
    source_id: int
    dest_id: int
