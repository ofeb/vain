from __future__ import annotations

from typing import TypedDict

_WEBHOOK_NAME = "vain - uwulock"
_COOLDOWN_SECONDS = 3
_MAX_LENGTH = 2000


class Record(TypedDict, total=False):
    guild_id: int
    user_id: int


__all__ = ["_WEBHOOK_NAME", "_COOLDOWN_SECONDS", "_MAX_LENGTH", "Record"]
