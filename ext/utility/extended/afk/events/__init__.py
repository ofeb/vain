from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord.utils import format_dt

from core.discord.package import Package
from config import color

from ..settings import AFK

from core.discord.views.embed import c2

if TYPE_CHECKING:
    from core.vain import Vain


class AFKEvents:
    def _store(self) -> AFK | None:
        redis = getattr(self.bot, "redis", None)
        if redis is None:
            return None
        return AFK(redis)

    @Package.listener("on_message")
    async def afk_dispatch(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        store = self._store()
        if store is None:
            return
        if not await store.exists(message.author.id):
            return
        data = await store.get(message.author.id)
        if not data:
            return
        if await store.remove(message.author.id):
            mentions = await store.get_mentions(message.author.id)
            view = None
            if mentions:
                from .. import views as afk_views
                view = afk_views.AFKMentionsButton(owner_id=message.author.id, bot=self.bot)
            embed = c2(
                message=(
                    f"{message.author.mention}: Welcome back, you were away "
                    f"for {format_dt(data.timestamp, 'R')}."
                ),
                timestamp=False,
            )
            embed.color = None
            await message.reply(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=30 if view is None else None,
            )

    @Package.listener("on_message")
    async def afk_check(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.mentions:
            return
        store = self._store()
        if store is None:
            return
        redis = self.bot.redis
        try:
            if await redis.ratelimited(f"afk:ratelimited:{message.channel.id}", 1, 5):
                return
        except Exception:
            pass

        for user in message.mentions:
            if user.bot or user.id == message.author.id:
                continue
            if not await store.exists(user.id):
                continue
            data = await store.get(user.id)
            if not data:
                continue
            
            try:
                await store.add_mention(
                    user.id,
                    author_id=message.author.id,
                    author_name=str(message.author),
                    jump_url=message.jump_url,
                    channel_id=message.channel.id,
                    content=message.content or "",
                    timestamp=message.created_at.timestamp(),
                )
            except Exception:
                pass
            embed = c2(
                message=(
                    f"{user.mention} is AFK: **{data.status}** - "
                    f"{format_dt(data.timestamp, 'R')}"
                ),
                timestamp=False,
            )
            embed.color = None
            await message.reply(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
