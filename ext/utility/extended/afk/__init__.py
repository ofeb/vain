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
        description="set yourself as away from keyboard\n use --global to set yourself afk in all servers",
        aliases=["away"],
        invoke_without_command=True,
    )
    @describe(status="What you're doing and why")
    async def afk(self, ctx: Context, *, status: str = "AFK") -> None:
        if ctx.invoked_subcommand is not None:
            return

        is_global = "--global" in status or "--g" in status
        if is_global:
            status = status.replace("--global", "").replace("--g", "").strip() or "AFK"
            guild_id = None
            scope_label = "globally"
        else:
            guild_id = ctx.guild.id
            scope_label = f""

        store = self._store()
        await store.set(ctx.author.id, status or "AFK", guild_id=guild_id)
        embed = c2(
            message=f"You're now **afk** {scope_label} - {status or 'AFK'}",
            timestamp=False,
        )
        embed.color = None
        await ctx.send(embed=embed)

    @afk.command(
        name="mentions",
        aliases=["pings", "mentionslist", "ml"],
        description="view mentions you received while afk",
    )
    async def afk_mentions(self, ctx: Context) -> None:
        store = self._store()
        mentions = await store.get_mentions(ctx.author.id, guild_id=ctx.guild.id)
        if not mentions:
            return await ctx.warn("No AFK mentions recorded for your last session")
        pages = build_afk_mention_pages(
            mentions,
            owner_mention=ctx.author.mention,
            bot=self.bot,
        )
        return await send_pages(ctx, pages)


async def setup(bot: "Vain") -> None:
    await bot.add_cog(Away(bot))


__all__ = ["Away", "setup", "c2"]
