from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class PrefixConfig:
    guild_id: int
    prefixes: List[str] = field(default_factory=lambda: [","])
    self_prefix: str | None = None
