"""Vanity models."""

from __future__ import annotations

from typing import TypedDict


class VanityRecord(TypedDict, total=False):
    guild_id: int
    channel_id: int | None
    role_ids: list[int]
    template: str | None


__all__ = ["VanityRecord"]
