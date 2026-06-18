from __future__ import annotations
from dataclasses import dataclass


@dataclass
class StickerRecord:
    guild_id: int
    sticker_id: int
    name: str
