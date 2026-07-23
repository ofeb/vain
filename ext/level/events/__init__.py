from __future__ import annotations

import logging
import random

import discord

from core.discord.package import Package

from .. import XP_COOLDOWN, XP_PER_MESSAGE, level_from_xp
from ..settings import Settings as LevelSettings

log = logging.getLogger("vain.level.events")


class LevelEvents:
    @Package.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        
        now = message.created_at.timestamp()
        last = self._cooldowns.get(message.author.id, 0)
        if now - last < XP_COOLDOWN:
            return

        try:
            settings = await LevelSettings.fetch(self.bot, message.guild)
            if not settings.enabled:
                return

            self._cooldowns[message.author.id] = now
            mult = max(1, int(settings.multiplier or 1))
            xp_gained = max(1, (XP_PER_MESSAGE + random.randint(-5, 5)) * mult)

            row = await self.bot.db.fetchrow(
                "SELECT xp FROM levels WHERE guild_id = $1 AND user_id = $2",
                message.guild.id,
                message.author.id,
            )
            old_xp = int(row["xp"]) if row else 0
            new_xp = old_xp + xp_gained
            old_level = level_from_xp(old_xp)
            new_level = level_from_xp(new_xp)

            await self.bot.db.execute(
                """
                INSERT INTO levels (guild_id, user_id, xp, level, updated_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    xp = EXCLUDED.xp,
                    level = EXCLUDED.level,
                    updated_at = CURRENT_TIMESTAMP
                """,
                message.guild.id,
                message.author.id,
                new_xp,
                new_level,
            )

            if new_level > old_level:
                roles = await self.bot.db.fetch(
                    "SELECT role_id, level FROM level_roles WHERE guild_id = $1 AND level = $2",
                    message.guild.id,
                    new_level,
                )
                for r in roles:
                    role = message.guild.get_role(int(r["role_id"]))
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason="Level reward")
                        except Exception:
                            pass
        except Exception:
            log.exception(
                "xp grant failed guild=%s user=%s",
                getattr(message.guild, "id", None),
                message.author.id,
            )
