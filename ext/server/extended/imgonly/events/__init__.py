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
        self._imgonly_last_sent: dict[tuple[int, int], float] = {}
        self._imgonly_delete_queue: dict[int, list[discord.Message]] = {}
        self._imgonly_delete_tasks: dict[int, asyncio.Task] = {}

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

        channel_id = message.channel.id
        user_id = message.author.id
        now = time.time()
        key = (channel_id, user_id)

        last_sent = self._imgonly_last_sent.get(key, 0)
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
        else:
            text = f"{message.author.mention} only **attachments** are allowed in {message.channel.mention}"

        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            sent = await message.channel.send(text)
            self._queue_for_deletion(sent, 180)

    def _queue_for_deletion(self, message: discord.Message, delay: float) -> None:
        channel_id = message.channel.id
        if channel_id not in self._imgonly_delete_queue:
            self._imgonly_delete_queue[channel_id] = []
        self._imgonly_delete_queue[channel_id].append(message)
        self._process_queue(channel_id)

    def _process_queue(self, channel_id: int) -> None:
        if channel_id in self._imgonly_delete_tasks:
            return
        self._imgonly_delete_tasks[channel_id] = asyncio.create_task(
            self._delete_queue_loop(channel_id)
        )

    async def _delete_queue_loop(self, channel_id: int) -> None:
        while True:
            queue = self._imgonly_delete_queue.get(channel_id, [])
            if not queue:
                break
            msg = queue.pop(0)
            with contextlib.suppress(discord.HTTPException, discord.NotFound):
                await msg.delete()
            await asyncio.sleep(1)
        self._imgonly_delete_tasks.pop(channel_id, None)
        self._imgonly_delete_queue.pop(channel_id, None)
