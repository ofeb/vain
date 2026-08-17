from __future__ import annotations

import contextlib
import discord
from core.discord.package import Package


class ImgonlyEvents(Package):
    """imgonly event listeners."""

    @Package.listener("on_message")
    async def on_imgonly_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        row = await self.db.fetchrow(
            "SELECT 1 FROM image_only WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        )
        if not row:
            return

        if message.attachments:
            return

        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} only **attachments** are allowed in {message.channel.mention}",
                delete_after=5,
            )
