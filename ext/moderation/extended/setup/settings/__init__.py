from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.vain import Vain

__all__: list[str] = ["Settings"]


class Settings:
    """DB helpers for the setup cog — writes to modlog_config, log_config, server_settings."""

    @staticmethod
    async def set_modlog_channel(db: Any, guild_id: int, channel_id: int) -> None:
        await db.execute(
            """INSERT INTO modlog_config (guild_id, channel_id)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2""",
            guild_id,
            channel_id,
        )

    @staticmethod
    async def add_log_events(db: Any, guild_id: int, channel_id: int, events: list[str]) -> None:
        ok = False
        for evt in events:
            try:
                await db.execute(
                    """INSERT INTO log_config (guild_id, channel_id, events)
                       VALUES ($1, $2, ARRAY[$3])
                       ON CONFLICT (guild_id, channel_id) DO UPDATE
                       SET events = array_append(log_config.events, $3)
                       WHERE NOT (log_config.events @> ARRAY[$3])""",
                    guild_id,
                    channel_id,
                    evt,
                )
                ok = True
            except Exception:
                continue
        if not ok:
            await db.execute(
                """INSERT INTO log_config (guild_id, channel_id, events)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id, channel_id) DO UPDATE
                   SET events = EXCLUDED.events""",
                guild_id,
                channel_id,
                events,
            )

    @staticmethod
    async def set_jail_log_channel(db: Any, guild_id: int, jail_log_channel_id: int) -> None:
        await db.execute(
            """UPDATE server_settings
               SET jail_log_channel_id = $2
               WHERE guild_id = $1""",
            guild_id,
            jail_log_channel_id,
        )

    @staticmethod
    async def set_jail_config(db: Any, guild_id: int, jail_channel_id: int, jail_role_id: int) -> None:
        await db.execute(
            """INSERT INTO server_settings (guild_id, jail_channel_id, jail_role_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id) DO UPDATE
               SET jail_channel_id = $2, jail_role_id = $3""",
            guild_id,
            jail_channel_id,
            jail_role_id,
        )

    @staticmethod
    async def set_mute_roles(db: Any, guild_id: int, imuted_role_id: int, rmuted_role_id: int) -> None:
        await db.execute(
            """INSERT INTO server_settings (guild_id, imuted_role_id, rmuted_role_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id) DO UPDATE
               SET imuted_role_id = $2, rmuted_role_id = $3""",
            guild_id,
            imuted_role_id,
            rmuted_role_id,
        )

    @staticmethod
    async def clear_modlog_config(db: Any, guild_id: int) -> None:
        await db.execute(
            "DELETE FROM modlog_config WHERE guild_id = $1", guild_id
        )

    @staticmethod
    async def clear_log_config(db: Any, guild_id: int) -> None:
        await db.execute(
            "DELETE FROM log_config WHERE guild_id = $1", guild_id
        )

    @staticmethod
    async def clear_jail_and_mute_config(db: Any, guild_id: int) -> None:
        await db.execute(
            """UPDATE server_settings
               SET jail_channel_id = NULL, jail_role_id = NULL,
                   muted_role_id = NULL, imuted_role_id = NULL, rmuted_role_id = NULL,
                   antinuke_log_channel_id = NULL, antiraid_log_channel_id = NULL
               WHERE guild_id = $1""",
            guild_id,
        )
