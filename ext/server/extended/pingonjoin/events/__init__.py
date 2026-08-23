from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import discord
from discord import AllowedMentions, Member

from core.discord.package import Package


DEFAULT_DELETE_AFTER = 10  
DEFAULT_DELETE_ENABLED = True


class PingOnJoinEvents(Package):
    async def _ensure_table(self) -> None:
        with suppress(Exception):
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS pingonjoin (
                    guild_id BIGINT PRIMARY KEY,
                    channel_ids BIGINT[] NOT NULL DEFAULT '{}',
                    message TEXT,
                    delete_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    delete_after INT NOT NULL DEFAULT 10
                )
                """
            )
        
        for sql in (
            "ALTER TABLE pingonjoin ADD COLUMN IF NOT EXISTS message TEXT",
            "ALTER TABLE pingonjoin ADD COLUMN IF NOT EXISTS delete_enabled BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE pingonjoin ADD COLUMN IF NOT EXISTS delete_after INT NOT NULL DEFAULT 10",
        ):
            with suppress(Exception):
                await self.bot.db.execute(sql)

    async def _get_pingonjoin_row(self, guild_id: int) -> dict[str, Any]:
        await self._ensure_table()
        with suppress(Exception):
            row = await self.bot.db.fetchrow(
                "SELECT * FROM pingonjoin WHERE guild_id = $1",
                guild_id,
            )
            if row:
                return dict(row)
        return {
            "guild_id": guild_id,
            "channel_ids": [],
            "message": None,
            "delete_enabled": DEFAULT_DELETE_ENABLED,
            "delete_after": DEFAULT_DELETE_AFTER,
        }

    async def _get_channels(self, guild_id: int) -> list[int]:
        row = await self._get_pingonjoin_row(guild_id)
        ids = row.get("channel_ids") or []
        return [int(i) for i in ids]

    async def _set_channels(self, guild_id: int, channel_ids: list[int]) -> None:
        await self._ensure_table()
        await self.bot.db.execute(
            """
            INSERT INTO pingonjoin (guild_id, channel_ids)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET channel_ids = EXCLUDED.channel_ids
            """,
            guild_id,
            channel_ids,
        )

    async def _set_message(self, guild_id: int, message: str | None) -> None:
        await self._ensure_table()
        await self.bot.db.execute(
            """
            INSERT INTO pingonjoin (guild_id, message)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET message = EXCLUDED.message
            """,
            guild_id,
            message,
        )

    async def _set_delete(
        self,
        guild_id: int,
        *,
        enabled: bool | None = None,
        after: int | None = None,
    ) -> None:
        await self._ensure_table()
        row = await self._get_pingonjoin_row(guild_id)
        en = row.get("delete_enabled", DEFAULT_DELETE_ENABLED) if enabled is None else enabled
        sec = row.get("delete_after", DEFAULT_DELETE_AFTER) if after is None else after
        sec = max(1, min(int(sec), 600))  
        await self.bot.db.execute(
            """
            INSERT INTO pingonjoin (guild_id, delete_enabled, delete_after)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET
                delete_enabled = EXCLUDED.delete_enabled,
                delete_after = EXCLUDED.delete_after
            """,
            guild_id,
            bool(en),
            int(sec),
        )

    async def _send_ping(self, channel: discord.abc.Messageable, member: Member, script: str | None):
        """Send either a custom script or a plain mention."""
        if script and str(script).strip():
            try:
                return await self.bot.send_embed(
                    channel,
                    script,
                    user=member,
                    member=member,
                    guild=member.guild,
                    channel=channel,
                )
            except Exception:
                
                pass
        return await channel.send(
            member.mention,
            allowed_mentions=AllowedMentions(users=True),
        )

    @Package.listener("on_member_join")
    async def on_member_join_ping(self, member: Member) -> None:
        if member.bot:
            return
        row = await self._get_pingonjoin_row(member.guild.id)
        ids = [int(i) for i in (row.get("channel_ids") or [])]
        if not ids:
            return

        script = row.get("message")
        delete_enabled = bool(row.get("delete_enabled", DEFAULT_DELETE_ENABLED))
        delete_after = int(row.get("delete_after") or DEFAULT_DELETE_AFTER)
        delete_after = max(1, min(delete_after, 600))

        for cid in ids:
            ch = member.guild.get_channel(cid)
            if ch is None:
                continue
            with suppress(discord.Forbidden, discord.HTTPException, Exception):
                msg = await self._send_ping(ch, member, script)
                if delete_enabled and msg is not None:
                    async def _delete_later(m: discord.Message, delay: int) -> None:
                        await asyncio.sleep(delay)
                        with suppress(discord.HTTPException, discord.NotFound, discord.Forbidden):
                            await m.delete()

                    asyncio.create_task(_delete_later(msg, delete_after))
