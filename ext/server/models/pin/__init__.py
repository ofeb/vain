from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PinConfig:
    guild_id: int
    archive_channel_id: int | None = None
    auto_unpin: bool = False
    dm_on_pin: bool = False
