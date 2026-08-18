"""AFK cog - global away status with mention notices (Redis)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group
from core.discord.package import Package
from core.discord.views.paginate import send_pages

from .events import AFKEvents
from .settings import AFK
from .views import build_afk_mention_pages

from core.discord.views.embed import c2

if TYPE_CHECKING:
    from core.vain import Vain


class Away(AFKEvents, Package):
    """Away-from-keyboard commands."""

    def __init__(self, bot: "Vain") -> None:
        Package.__init__(self, bot)

    def _store(self) -> AFK:
        if self.bot.redis is None:
            raise commands.CommandError("Redis is not connected - AFK is unavailable.")
        return AFK(self.bot.redis)

    @group(
        name="afk",
        description="Set yourself as away from keyboard",
        aliases=["away"],
        invoke_without_command=True,
    )
    @describe(status="What you're doing / why you're AFK")
    async def afk(self, ctx: Context, *, status: str = "AFK") -> None:
        if ctx.invoked_subcommand is not None:
            return
        store = self._store()
        await store.set(ctx.author.id, status or "AFK")
        embed = c2(
            message=f"You're now **afk** - {status or 'AFK'}",
            timestamp=False,
        )
        embed.color = None
        await ctx.send(embed=embed)

    @afk.command(
        name="mentions",
        aliases=["pings", "mentionslist", "ml"],
        description="View mentions you received while AFK",
    )
    async def afk_mentions(self, ctx: Context) -> None:
        store = self._store()
        mentions = await store.get_mentions(ctx.author.id)
        if not mentions:
            return await ctx.warn("No AFK mentions recorded for your last session")
        pages = build_afk_mention_pages(
            mentions,
            owner_mention=ctx.author.mention,
        )
        return await send_pages(ctx, pages)


async def setup(bot: "Vain") -> None:
    await bot.add_cog(Away(bot))


__all__ = ["Away", "setup", "c2"]
