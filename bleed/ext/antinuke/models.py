from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}


@dataclass(slots=True)
class ModuleConfig:
    status: bool = False
    punishment: str | None = None
    threshold: int = 3
    command: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "ModuleConfig":
        data = _coerce_dict(value)
        threshold = data.get("threshold", 3)
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = 3
        return cls(
            status=bool(data.get("status", False)),
            punishment=str(data["punishment"]).lower() if data.get("punishment") else None,
            threshold=threshold,
            command=bool(data.get("command", False)),
        )


@dataclass(slots=True)
class PermissionWatch:
    type: str
    permission: str
    punishment: str

    @classmethod
    def from_value(cls, value: Any) -> "PermissionWatch | None":
        data = _coerce_dict(value)
        kind = str(data.get("type", "")).lower()
        permission = str(data.get("permission", "")).lower()
        punishment = str(data.get("punishment", "kick")).lower()
        if not kind or not permission:
            return None
        return cls(type=kind, permission=permission, punishment=punishment)

    def as_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "permission": self.permission,
            "punishment": self.punishment,
        }


@dataclass(slots=True)
class AntinukeConfig:
    guild_id: int | None = None
    whitelist: list[int] = field(default_factory=list)
    admins: list[int] = field(default_factory=list)
    botadd: ModuleConfig = field(default_factory=ModuleConfig)
    webhook: ModuleConfig = field(default_factory=ModuleConfig)
    emoji: ModuleConfig = field(default_factory=ModuleConfig)
    ban: ModuleConfig = field(default_factory=ModuleConfig)
    kick: ModuleConfig = field(default_factory=ModuleConfig)
    channel: ModuleConfig = field(default_factory=ModuleConfig)
    role: ModuleConfig = field(default_factory=ModuleConfig)
    vanity: ModuleConfig = field(default_factory=ModuleConfig)
    permissions: list[PermissionWatch] = field(default_factory=list)

    @classmethod
    def from_record(cls, record: Any) -> "AntinukeConfig":
        if not record:
            return cls()

        data = dict(record)
        permissions: list[PermissionWatch] = []
        for value in data.get("permissions") or []:
            if item := PermissionWatch.from_value(value):
                permissions.append(item)

        return cls(
            guild_id=data.get("guild_id"),
            whitelist=list(data.get("whitelist") or []),
            admins=list(data.get("admins") or []),
            botadd=ModuleConfig.from_value(data.get("botadd")),
            webhook=ModuleConfig.from_value(data.get("webhook")),
            emoji=ModuleConfig.from_value(data.get("emoji")),
            ban=ModuleConfig.from_value(data.get("ban")),
            kick=ModuleConfig.from_value(data.get("kick")),
            channel=ModuleConfig.from_value(data.get("channel")),
            role=ModuleConfig.from_value(data.get("role")),
            vanity=ModuleConfig.from_value(data.get("vanity")),
            permissions=permissions,
        )

    def enabled_modules(self) -> list[tuple[str, ModuleConfig]]:
        modules = [
            ("botadd", self.botadd),
            ("webhook", self.webhook),
            ("emoji", self.emoji),
            ("ban", self.ban),
            ("kick", self.kick),
            ("channel", self.channel),
            ("role", self.role),
            ("vanity", self.vanity),
        ]
        return [(name, module) for name, module in modules if module.status]

    def enabled_count(self) -> int:
        return len(self.enabled_modules())

    def permission_count(self, kind: str) -> int:
        return sum(1 for item in self.permissions if item.type == kind)
