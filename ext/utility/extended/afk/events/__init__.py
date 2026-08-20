from __future__ import annotations

import contextlib
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
        if not await store.exists_any(message.author.id, guild_id=message.guild.id):
            return
        data = await store.get_any(message.author.id, guild_id=message.guild.id)
        if not data:
            return
        if await store.remove_any(message.author.id, guild_id=message.guild.id):
            mentions = await store.get_mentions(message.author.id, guild_id=message.guild.id)
            view = None
            if mentions:
                from .. import views as afk_views
                view = afk_views.AFKMentionsButton(owner_id=message.author.id, bot=self.bot, guild_id=message.guild.id)
            text = (
                f"{message.author.mention}: Welcome back, you were away "
                f"for {format_dt(data.timestamp, 'R')}."
            )
            await message.channel.send(
                content=None,
                view=self._build_afk_layout(text, view=view),
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
            if not await store.exists_any(user.id, guild_id=message.guild.id):
                continue
            data = await store.get_any(user.id, guild_id=message.guild.id)
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
                    guild_id=message.guild.id,
                )
            except Exception:
                pass
            text = (
                f"{user.mention} is AFK: **{data.status}** - "
                f"{format_dt(data.timestamp, 'R')}"
            )
            from discord import ui as _ui
            from core.discord.ctx import layout_from_items
            container = _ui.Container()
            for attr in ("accent_color", "accent_colour", "color", "colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(_ui.TextDisplay(text))
            layout = layout_from_items([container], timeout=None)
            await message.channel.send(
                view=layout,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    def _build_afk_layout(self, text: str, view=None):
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        container = _ui.Container()
        for attr in ("accent_color", "accent_colour", "color", "colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(text))
        layout = layout_from_items([container], timeout=None)
        if view is not None:
            return layout
        return layout
