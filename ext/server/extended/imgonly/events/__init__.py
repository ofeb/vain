from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import discord

from core.discord.package import Package
from ..settings import Settings

log = logging.getLogger("vain.server.extended.imgonly")


class ImgonlyEvents(Package):
    """imgonly / gallery event listeners.

    State is kept on the class so it works when mixed into ``Server``
    (mixin ``__init__`` is not called by the Server cog).
    """

    _imgonly_last_sent: dict[tuple[int, int], float] = {}
    _imgonly_delete_tasks: dict[int, set[asyncio.Task]] = {}
    _imgonly_schema_ready: bool = False

    async def _ensure_imgonly_schema(self) -> None:
        if ImgonlyEvents._imgonly_schema_ready:
            return
        try:
            await Settings.ensure_schema(self.db)
            ImgonlyEvents._imgonly_schema_ready = True
        except Exception:
            log.exception("imgonly schema ensure failed")

    
    @Package.listener("on_message")
    async def on_imgonly_message(self, message: discord.Message) -> None:
        try:
            if message.author.bot or not message.guild:
                return
            if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
                return
            if self._can_bypass(message):
                return

            await self._ensure_imgonly_schema()


            channel = message.channel
            channel_id = channel.id
            if isinstance(channel, discord.Thread):
                channel_id = channel.parent_id or channel.id

            try:
                row = await self.db.fetchrow(
                    "SELECT 1 FROM image_only WHERE guild_id = $1 AND channel_id = $2",
                    message.guild.id,
                    channel_id,
                )
            except Exception:
                log.exception("image_only lookup failed")
                return

            if not row:
                return

            if self._has_media(message):
                return


            with contextlib.suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
                await message.delete()


            user_id = message.author.id
            now = time.time()
            key = (channel_id, user_id)
            last_sent = ImgonlyEvents._imgonly_last_sent.get(key, 0.0)
            if now - last_sent < 15:
                return
            ImgonlyEvents._imgonly_last_sent[key] = now

            text = await self._warning_text(message, channel_id)

            send_channel = message.channel
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                sent = await send_channel.send(text)
                self._schedule_delete(sent, delay=60.0)

        except Exception:
            log.exception("on_imgonly_message failed")

    async def _warning_text(self, message: discord.Message, channel_id: int) -> str:
        try:
            msg_row = await self.db.fetchrow(
                "SELECT message FROM image_only_messages WHERE guild_id = $1 AND channel_id = $2",
                message.guild.id,
                channel_id,
            )
        except Exception:
            msg_row = None

        custom = None
        if msg_row is not None:

            custom = msg_row["message"] if "message" in msg_row else getattr(msg_row, "message", None)

        if custom and str(custom).strip():
            text = str(custom)
            return (
                text.replace("{user}", message.author.mention)
                .replace("{channel}", message.channel.mention)
                .replace("{guild}", message.guild.name if message.guild else "")
            )

        return (
            f"> {message.author.mention} this is a **gallery** channel\n"
            f"> -# only **images or attachments** are allowed in {message.channel.mention}"
        )

    def _schedule_delete(self, message: discord.Message, delay: float) -> None:
        """Delete the warning message after `delay` seconds."""
        channel_id = message.channel.id

        async def _later() -> None:
            try:
                await asyncio.sleep(delay)
                with contextlib.suppress(
                    discord.HTTPException, discord.NotFound, discord.Forbidden
                ):
                    await message.delete()
            finally:
                tasks = ImgonlyEvents._imgonly_delete_tasks.get(channel_id)
                if tasks is not None:
                    cur = asyncio.current_task()
                    if cur is not None:
                        tasks.discard(cur)
                    if not tasks:
                        ImgonlyEvents._imgonly_delete_tasks.pop(channel_id, None)

        task = asyncio.create_task(_later())
        ImgonlyEvents._imgonly_delete_tasks.setdefault(channel_id, set()).add(task)
