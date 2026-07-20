from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.utils import format_dt

from core.discord.package import Package
from core.managers.values import color

from ..settings import AFK

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
            embed = c2(
                color=color.approve,
                message=(
                    f"{message.author.mention}: Welcome back, you were away "
                    f"for {format_dt(data.timestamp, 'R')}."
                ),
                timestamp=False,
            )
            await message.reply(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=15,
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
            if user.bot:
                continue
            if not await store.exists(user.id):
                continue
            data = await store.get(user.id)
            if not data:
                continue
            embed = c2(
                color=color.approve,
                message=(
                    f"{user.mention} is AFK: **{data.status}** — "
                    f"{format_dt(data.timestamp, 'R')}"
                ),
                timestamp=False,
            )
            await message.reply(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )


def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def c2(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed



