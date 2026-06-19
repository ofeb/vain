from __future__ import annotations

import platform
from typing import TYPE_CHECKING

import discord

from core.discord.ctx import Context
from core.discord.hybrid import hybrid
from core.discord.package import Package
from core.managers.values import color

if TYPE_CHECKING:
    from core.bleed import Bleed


class InformationCommands(Package):
    """base mixin for standalone information commands."""

    def __init__(self, bot: Bleed):
        super().__init__(bot)

    @hybrid(
        name="botinfo",
        description="View information about the bot",
        aliases=["bi", "stats"],
    )
    async def botinfo(self, ctx: Context) -> None:
        bot = self.bot
        total_commands = len(set(bot.walk_commands()))
        guilds = len(bot.guilds)
        users = sum(g.member_count or 0 for g in bot.guilds)
        latency = round(bot.latency * 1000)
        uptime = discord.utils.format_dt(bot.started_at, style="R")

        embed = discord.Embed(
            color=color.base,
            description=(
                f"## {bot.user.display_name if bot.user else 'Bleed'}\n"
                f"-# Commands » `{total_commands}`\n"
                f"-# Latency » `{latency}ms`\n"
                f"-# Uptime » {uptime}\n"
                f"-# Servers » `{guilds:,}`\n"
                f"-# Users » `{users:,}`\n"
            ),
        )
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Website",
            style=discord.ButtonStyle.link,
            url="https://bleed.bot",
            emoji="\U0001f310",
        ))
        view.add_item(discord.ui.Button(
            label="Invite",
            style=discord.ButtonStyle.link,
            url=f"https://discord.com/oauth2/authorize?client_id={bot.user.id}&scope=bot+applications.commands&permissions=8" if bot.user else discord.Embed.Empty,
            emoji="\U0001f517",
        ))
        await ctx.send(embed=embed, view=view)
