from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ModuleConfig:
    enabled: bool = False
    threshold: int = 0
    action: str | None = None
    lock_channels: bool = False
    punish_new: bool = False

    @classmethod
    def from_record(cls, record: Any, *, threshold: int, action: str) -> "ModuleConfig":
        if not record:
            return cls(threshold=threshold, action=action)

        data = dict(record)
        return cls(
            enabled=bool(data.get("enabled", False)),
            threshold=int(data.get("threshold") or threshold),
            action=str(data.get("action") or action).lower(),
            lock_channels=bool(data.get("lock_channels", False)),
            punish_new=bool(data.get("punish_new", False)),
        )


@dataclass(slots=True)
class AntiraidConfig:
    raid_active: bool = False
    punish_until: datetime | None = None
    massjoin: ModuleConfig = field(
        default_factory=lambda: ModuleConfig(threshold=5, action="ban")
    )
    avatar: ModuleConfig = field(
        default_factory=lambda: ModuleConfig(threshold=0, action="kick")
    )
    newaccounts: ModuleConfig = field(
        default_factory=lambda: ModuleConfig(threshold=7, action="ban")
    )

    @classmethod
    def from_records(
        cls,
        config_row: Any,
        module_rows: list[Any],
    ) -> "AntiraidConfig":
        config_data = dict(config_row) if config_row else {}
        config = cls(
            raid_active=bool(config_data.get("raid_active", False)),
            punish_until=config_data.get("punish_until"),
        )

        module_map = {str(row.module): row for row in module_rows}
        config.massjoin = ModuleConfig.from_record(
            module_map.get("massjoin"),
            threshold=5,
            action="ban",
        )
        config.avatar = ModuleConfig.from_record(
            module_map.get("avatar"),
            threshold=0,
            action="kick",
        )
        config.newaccounts = ModuleConfig.from_record(
            module_map.get("newaccounts"),
            threshold=7,
            action="ban",
        )
        return config
