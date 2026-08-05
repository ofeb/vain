from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class FilterConfig:
    guild_id: int
    filter_type: str
    enabled: bool = False
    threshold: int = 0
    channel_ids: List[int] = field(default_factory=list)
    exempt_role_ids: List[int] = field(default_factory=list)


@dataclass
class WordFilterRecord:
    guild_id: int
    word: str
    is_regex: bool = False
