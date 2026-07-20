from __future__ import annotations

import datetime

import discord

from core.discord.package import Package

from ..constants import BUMP_COOLDOWN, DISBOARD_ID


class BumpReminderEvents:
    @Package.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.id != DISBOARD_ID or not message.guild:
            return

        guild_id = message.guild.id
        if guild_id not in self._cache:
            return

        if "Bump done" in message.content or "bump done" in message.content:
            self._cache[guild_id]["last_bump"] = discord.utils.utcnow()
            self._cache[guild_id]["next_bump"] = discord.utils.utcnow() + datetime.timedelta(seconds=BUMP_COOLDOWN)
            self._cache[guild_id]["bump_channel_id"] = message.channel.id

            channel = self.bot.get_channel(self._cache[guild_id]["channel_id"])
            if channel:
                await channel.send("Bump successful! Next bump available in 2 hours.")

