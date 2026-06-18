from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RoleRecord:
    guild_id: int
    role_id: int
    action: str
