from __future__ import annotations

import asyncio
import contextlib
import time
import discord
from core.discord.package import Package


class ImgonlyEvents(Package):
    """imgonly event listeners."""

    def __init__(self, bot):
        super().__init__(bot)
        # (channel_id, user_id) -> last warning timestamp
        self._imgonly_last_sent: dict[tuple[int, int], float] = {}
        # per-channel scheduled delete tasks
        self._imgonly_delete_tasks: dict[int, set[asyncio.Task]] = {}

    @Package.listener("on_message")
    async def on_imgonly_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        # members with manage_messages can post text freely
        if isinstance(message.author, discord.Member):
            perms = message.channel.permissions_for(message.author)
            if perms.manage_messages or perms.administrator:
                return

        row = await self.db.fetchrow(
            "SELECT 1 FROM image_only WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        )
        if not row:
            return

        # allow messages that include at least one attachment (image/video/file)
        if message.attachments:
            return

        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await message.delete()

        channel_id = message.channel.id
        user_id = message.author.id
        now = time.time()
        key = (channel_id, user_id)

        # rate-limit the warning to once per 60s per user per channel
        last_sent = self._imgonly_last_sent.get(key, 0.0)
        if now - last_sent < 60:
            return

        self._imgonly_last_sent[key] = now

        msg_row = await self.db.fetchrow(
            "SELECT message FROM image_only_messages WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            channel_id,
        )
        if msg_row and msg_row.message:
            text = msg_row.message
            # allow {user} / {channel} placeholders in custom scripts
            text = (
                text.replace("{user}", message.author.mention)
                .replace("{channel}", message.channel.mention)
                .replace("{guild}", message.guild.name)
            )
        else:
            text = (
                f"{message.author.mention} this is a **gallery** channel — "
                f"only **attachments** are allowed in {message.channel.mention}"
            )

        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            sent = await message.channel.send(text)
            self._schedule_delete(sent, delay=15.0)

    def _schedule_delete(self, message: discord.Message, delay: float) -> None:
        """Delete the warning message after `delay` seconds (does not block)."""
        channel_id = message.channel.id

        async def _later() -> None:
            try:
                await asyncio.sleep(delay)
                with contextlib.suppress(discord.HTTPException, discord.NotFound, discord.Forbidden):
                    await message.delete()
            finally:
                tasks = self._imgonly_delete_tasks.get(channel_id)
                if tasks is not None:
                    tasks.discard(asyncio.current_task())
                    if not tasks:
                        self._imgonly_delete_tasks.pop(channel_id, None)

        task = asyncio.create_task(_later())
        self._imgonly_delete_tasks.setdefault(channel_id, set()).add(task)
