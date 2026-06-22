from __future__ import annotations

import discord

from core.discord.package import Package


class LevelEvents:
    @Package.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        now = message.created_at.timestamp()
        last = self._cooldowns.get(message.author.id, 0)
        if now - last < XP_COOLDOWN:
            return

        self._cooldowns[message.author.id] = now
        xp_gained = XP_PER_MESSAGE + random.randint(-5, 5)

        try:
            row = await self.bot.db.fetchrow(
                "SELECT xp FROM levels WHERE guild_id = $1 AND user_id = $2",
                message.guild.id, message.author.id,
            )
            old_xp = row[0] if row else 0
            new_xp = old_xp + xp_gained
            old_level = level_from_xp(old_xp)
            new_level = level_from_xp(new_xp)

            await self.bot.db.execute(
                """INSERT INTO levels (guild_id, user_id, xp)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = $3""",
                message.guild.id, message.author.id, new_xp,
            )

            if new_level > old_level:
                roles = await self.bot.db.fetch(
                    "SELECT role_id, level FROM level_roles WHERE guild_id = $1 AND level = $2",
                    message.guild.id, new_level,
                )
                for row in roles:
                    role = message.guild.get_role(row[0])
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason="Level reward")
                        except Exception:
                            pass
        except Exception:
            pass

