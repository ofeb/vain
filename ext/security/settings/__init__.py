from __future__ import annotations

from logging import getLogger
from typing import Any

from discord import Guild

from core.vain import Vain
from ..models import AntinukeConfig, ModuleConfig, PermissionWatch

logger = getLogger("vain.antinuke.settings")


def _mod_dict(m: Any) -> dict[str, Any]:
    if isinstance(m, ModuleConfig):
        return {
            "status": bool(m.status),
            "punishment": m.punishment,
            "threshold": int(m.threshold or 3),
            "command": bool(m.command),
        }
    if isinstance(m, dict):
        return dict(m)
    return {
        "status": bool(getattr(m, "status", False)),
        "punishment": getattr(m, "punishment", None),
        "threshold": int(getattr(m, "threshold", 3) or 3),
        "command": bool(getattr(m, "command", False)),
    }


class Settings:
    """Antinuke configuration for one guild."""

    bot: Vain
    guild: Guild
    record: dict[str, Any]
    config: AntinukeConfig

    def __init__(
        self,
        bot: Vain,
        guild: Guild,
        record: dict[str, Any] | None = None,
        *,
        config: AntinukeConfig | None = None,
    ) -> None:
        self.bot = bot
        self.guild = guild
        if config is not None:
            self.config = config
            self.config.guild_id = guild.id
            self.record = {
                "guild_id": guild.id,
                "whitelist": list(config.whitelist or []),
                "admins": list(config.admins or []),
                "botadd": _mod_dict(config.botadd),
                "webhook": _mod_dict(config.webhook),
                "emoji": _mod_dict(config.emoji),
                "ban": _mod_dict(config.ban),
                "kick": _mod_dict(config.kick),
                "channel": _mod_dict(config.channel),
                "role": _mod_dict(config.role),
                "vanity": _mod_dict(config.vanity),
                "permissions": [
                    p.as_dict() if hasattr(p, "as_dict") else dict(p)
                    for p in (config.permissions or [])
                ],
            }
        else:
            self.record = dict(record or {"guild_id": guild.id})
            self.config = AntinukeConfig.from_record(self.record)
            self.config.guild_id = guild.id

    def __bool__(self) -> bool:
        return self.config.enabled_count() > 0 or bool(self.config.admins)

    @classmethod
    async def fetch(cls, bot: Vain, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM antinuke WHERE guild_id = $1",
            guild.id,
        )
        if not row:
            return cls(bot, guild, config=AntinukeConfig(guild_id=guild.id))
        cfg = AntinukeConfig.from_record(row)
        cfg.guild_id = guild.id
        return cls(bot, guild, dict(row), config=cfg)

    async def upsert(self, revalidate: bool = True, **kwargs: Any) -> Settings:
        cfg = kwargs.pop("config", None) or self.config
        if not isinstance(cfg, AntinukeConfig):
            cfg = self.config
        for key in ("whitelist", "admins"):
            if key in kwargs:
                setattr(cfg, key, list(kwargs[key]))
        for key in ("botadd", "webhook", "emoji", "ban", "kick", "channel", "role", "vanity"):
            if key in kwargs:
                setattr(cfg, key, ModuleConfig.from_value(kwargs[key]))
        if "permissions" in kwargs:
            watches = []
            for item in kwargs["permissions"] or []:
                w = item if isinstance(item, PermissionWatch) else PermissionWatch.from_value(item)
                if w:
                    watches.append(w)
            cfg.permissions = watches
        cfg.guild_id = self.guild.id
        perms = [
            p.as_dict() if hasattr(p, "as_dict") else dict(p)
            for p in (cfg.permissions or [])
        ]
        await self.bot.db.execute(
            """
            INSERT INTO antinuke (
                guild_id, whitelist, admins,
                botadd, webhook, emoji, ban, kick, channel, role, vanity, permissions
            ) VALUES (
                $1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb,
                $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb[]
            )
            ON CONFLICT (guild_id) DO UPDATE SET
                whitelist = EXCLUDED.whitelist,
                admins = EXCLUDED.admins,
                botadd = EXCLUDED.botadd,
                webhook = EXCLUDED.webhook,
                emoji = EXCLUDED.emoji,
                ban = EXCLUDED.ban,
                kick = EXCLUDED.kick,
                channel = EXCLUDED.channel,
                role = EXCLUDED.role,
                vanity = EXCLUDED.vanity,
                permissions = EXCLUDED.permissions
            """,
            self.guild.id,
            list(cfg.whitelist or []),
            list(cfg.admins or []),
            _mod_dict(cfg.botadd),
            _mod_dict(cfg.webhook),
            _mod_dict(cfg.emoji),
            _mod_dict(cfg.ban),
            _mod_dict(cfg.kick),
            _mod_dict(cfg.channel),
            _mod_dict(cfg.role),
            _mod_dict(cfg.vanity),
            perms,
        )
        self.config = cfg
        self.record = {
            "guild_id": self.guild.id,
            "whitelist": list(cfg.whitelist or []),
            "admins": list(cfg.admins or []),
            "botadd": _mod_dict(cfg.botadd),
            "webhook": _mod_dict(cfg.webhook),
            "emoji": _mod_dict(cfg.emoji),
            "ban": _mod_dict(cfg.ban),
            "kick": _mod_dict(cfg.kick),
            "channel": _mod_dict(cfg.channel),
            "role": _mod_dict(cfg.role),
            "vanity": _mod_dict(cfg.vanity),
            "permissions": perms,
        }
        if revalidate:
            logger.debug("upsert antinuke guild=%s", self.guild.id)
        return self

    async def insert(self, **kwargs: Any) -> Settings:
        return await self.upsert(**kwargs)


async def fetch(bot: Vain, guild: Guild | int) -> Settings | AntinukeConfig:
    if isinstance(guild, int):
        g = bot.get_guild(guild)
        if g is None:
            row = await bot.db.fetchrow(
                "SELECT * FROM antinuke WHERE guild_id = $1", guild
            )
            cfg = AntinukeConfig.from_record(row) if row else AntinukeConfig(guild_id=guild)
            cfg.guild_id = guild
            return cfg
        guild = g
    return await Settings.fetch(bot, guild)


async def upsert(bot: Vain, guild_or_config: Guild | AntinukeConfig, **kwargs: Any):
    if isinstance(guild_or_config, AntinukeConfig):
        guild = bot.get_guild(int(guild_or_config.guild_id or 0))
        if guild is None:
            
            settings = Settings.__new__(Settings)
            settings.bot = bot
            settings.guild = type("G", (), {"id": guild_or_config.guild_id})()  # type: ignore
            settings.record = {}
            settings.config = guild_or_config
            return await Settings.upsert(settings, config=guild_or_config)
        return await Settings(bot, guild, config=guild_or_config).upsert()
    settings = await Settings.fetch(bot, guild_or_config)
    return await settings.upsert(**kwargs)


async def insert(bot: Vain, guild: Guild | int, **kwargs: Any):
    return await upsert(bot, guild if not isinstance(guild, int) else guild, **kwargs)


__all__ = ["Settings", "fetch", "upsert", "insert"]
