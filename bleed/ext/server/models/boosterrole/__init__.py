from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BoosterRoleRecord:
    guild_id: int
    user_id: int
    role_id: int


@dataclass
class BoosterRoleConfig:
    guild_id: int
    base_role_id: int | None = None
    award_role_id: int | None = None
    limit: int = 0
