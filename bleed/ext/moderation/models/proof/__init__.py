from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ProofRecord:
    guild_id: int
    case_id: int
    media_url: str
    explanation: str
