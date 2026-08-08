from __future__ import annotations

import contextlib
import time
from asyncio import Lock
from collections import defaultdict
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package
from uwuipy import Uwuipy

from ..models import _COOLDOWN_SECONDS, _MAX_LENGTH, _WEBHOOK_NAME
from ..settings import Settings

if TYPE_CHECKING:
    from core.vain import Vain


class UwulockEvents(Package):
    """Deletes and uwuifies messages from locked members."""

    def __init__(self, bot: Vain) -> None:
        super().__init__(bot)
        self._locks: defaultdict[str, Lock] = defaultdict(Lock)
        self._last_send: dict[str, float] = {}

    async def _get_webhook(self, channel) -> discord.Webhook | None:
        target = channel.parent if isinstance(channel, discord.Thread) else channel
        if not isinstance(target, discord.TextChannel):
            return None
        try:
            webhooks = await target.webhooks()
        except (discord.Forbidden, discord.HTTPException):
            return None
        for webhook in webhooks:
            if webhook.user and webhook.user.id == self.bot.user.id and webhook.name == _WEBHOOK_NAME:
                return webhook
        try:
            return await target.create_webhook(
                name=_WEBHOOK_NAME,
                avatar=await self.bot.user.display_avatar.read(),
            )
        except (discord.Forbidden, discord.HTTPException):
            return None

    @Package.listener("on_message")
    async def on_uwulock_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return
        if getattr(self.db, "pool", None) is None:
            return
        if not message.content:
            return
        if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return

        settings = await Settings.fetch(self.bot, message.guild)
        if not settings.is_locked(message.author.id):
            return

        key = f"{message.guild.id}:{message.author.id}"
        lock = self._locks[key]
        if lock.locked():
            return

        last = self._last_send.get(key)
        if last is not None and time.monotonic() - last < _COOLDOWN_SECONDS:
            return

        self._last_send[key] = time.monotonic()

        async with lock:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException, discord.NotFound):
                await message.delete()

            try:
                result = Uwuipy().uwuify(message.content) or message.content
            except Exception:
                result = message.content
            result = result[:_MAX_LENGTH]

            webhook = await self._get_webhook(message.channel)
            if webhook is None:
                return
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await webhook.send(
                    result,
                    username=message.author.display_name,
                    avatar_url=message.author.display_avatar.url,
                    allowed_mentions=discord.AllowedMentions.none(),
                )


__all__ = ["UwulockEvents"]
