from __future__ import annotations
from dataclasses import dataclass


@dataclass
class SuggestConfig:
    guild_id: int
    channel_id: int
