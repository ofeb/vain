from __future__ import annotations
from dataclasses import dataclass


@dataclass
class EmojiRecord:
    guild_id: int
    emoji_id: int
    name: str
