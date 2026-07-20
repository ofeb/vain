"""AFK cog — global away status with mention notices (Redis)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.package import Package
from core.managers.values import color

from .events import AFKEvents
from .settings import AFK

if TYPE_CHECKING:
    from core.vain import Vain


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


class Away(AFKEvents, Package):
    """Away-from-keyboard commands."""

    def __init__(self, bot: "Vain") -> None:
        Package.__init__(self, bot)

    def _store(self) -> AFK:
        if self.bot.redis is None:
            raise commands.CommandError("Redis is not connected — AFK is unavailable.")
        return AFK(self.bot.redis)

    @hybrid(
        name="afk",
        description="Set yourself as away from keyboard",
        aliases=["away"],
    )
    @describe(status="What you're doing / why you're AFK")
    async def afk(self, ctx: Context, *, status: str = "AFK") -> None:
        store = self._store()
        await store.set(ctx.author.id, status or "AFK")
        embed = c2(
            color=color.base,
            message=f"You're now **afk** — {status or 'AFK'}",
            timestamp=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: "Vain") -> None:
    await bot.add_cog(Away(bot))


__all__ = ["Away", "setup", "c2"]
