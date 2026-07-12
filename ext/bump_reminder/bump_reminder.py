from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, Optional

import discord
from core.discord.package import Package, tasks

from .constants import BUMP_COOLDOWN, DISBOARD_ID
from .events import BumpReminderEvents

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid, group
from core.managers.permissions import has_permissions
from core.managers.values import color

if TYPE_CHECKING:
    from core.vain import Vain

class BumpReminder(BumpReminderEvents, Package):
    """Bump reminder commands to keep your server promoted."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._cache: dict[int, dict] = {}

    async def cog_load(self):
        self._bump_watcher.start()

    async def cog_unload(self):
        self._bump_watcher.stop()

    @tasks.loop(minutes=5)
    async def _bump_watcher(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        for guild_id, data in list(self._cache.items()):
            next_bump = data.get("next_bump")
            if not next_bump:
                continue
            if now >= next_bump:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                channel = guild.get_channel(data["channel_id"])
                if channel:
                    embed = discord.Embed(
                        title="Bump Ready!",
                        description="It's time to bump your server on DISBOARD!\nUse `;bump` in <#{}>".format(
                            data.get("bump_channel_id", "")
                        ),
                        color=color.base,
                    )
                    try:
                        await channel.send(embed=embed)
                    except Exception:
                        pass
                self._cache[guild_id]["next_bump"] = now + datetime.timedelta(seconds=BUMP_COOLDOWN)
    @group(
        name="bumpreminder",
        description="Configure the bump reminder system",
        guild_only=True,
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def bumpreminder(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @bumpreminder.command(
        name="channel",
        description="Set the reminder notification channel",
        guild_only=True,
    )
    @describe(channel="Channel to send reminders to")
    @has_permissions(manage_channels=True)
    async def bumpreminder_channel(self, ctx: Context, channel: discord.TextChannel) -> None:
        self._cache[ctx.guild.id] = {
            "channel_id": channel.id,
            "bump_channel_id": None,
            "last_bump": None,
            "next_bump": discord.utils.utcnow() + datetime.timedelta(seconds=BUMP_COOLDOWN),
        }
        embed = discord.Embed(
            title="Bump Reminder",
            description=f"Reminders will be sent to {channel.mention}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @bumpreminder.command(
        name="config",
        description="View bump reminder configuration",
        guild_only=True,
        aliases=["settings", "cfg"],
    )
    @has_permissions(manage_channels=True)
    async def bumpreminder_config(self, ctx: Context) -> None:
        data = self._cache.get(ctx.guild.id)
        if not data:
            await ctx.warn("Bump reminder is not configured.")
            return

        channel = ctx.guild.get_channel(data["channel_id"])
        last = data.get("last_bump")
        last_str = discord.utils.format_dt(last, style="R") if last else "Never"

        embed = discord.Embed(
            title="Bump Reminder Config",
            color=color.base,
        )
        embed.add_field(name="Reminder Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Last Bump", value=last_str, inline=True)
        await ctx.send(embed=embed)

    @bumpreminder.command(
        name="remove",
        description="Remove the bump reminder configuration",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def bumpreminder_remove(self, ctx: Context) -> None:
        self._cache.pop(ctx.guild.id, None)
        await ctx.success("Bump reminder removed.")

    @bumpreminder.command(
        name="thankyou",
        description="Set the 'Thank You' message for successfully running /bump",
        aliases=["ty"],
        guild_only=True,
    )
    @describe(message="The thank you message to send")
    @has_permissions(manage_channels=True)
    async def bumpreminder_thankyou(self, ctx: Context, *, message: str) -> None:
        if ctx.guild.id not in self._cache:
            self._cache[ctx.guild.id] = {}
        self._cache[ctx.guild.id]["thankyou_message"] = message
        await ctx.success(f"Thank you message set to: {message}")

    @bumpreminder.command(
        name="autoclean",
        description="Automatically delete messages that aren't /bump",
        guild_only=True,
    )
    @describe(choice="on or off")
    @has_permissions(manage_channels=True)
    async def bumpreminder_autoclean(self, ctx: Context, choice: str) -> None:
        if ctx.guild.id not in self._cache:
            self._cache[ctx.guild.id] = {}
        enabled = choice.lower() in ("on", "true", "enable", "1")
        self._cache[ctx.guild.id]["autoclean"] = enabled
        await ctx.success(f"Autoclean {'enabled' if enabled else 'disabled'}.")

    @bumpreminder.command(
        name="autolock",
        description="Lock channel until ready to use /bump",
        guild_only=True,
    )
    @describe(choice="on or off")
    @has_permissions(manage_channels=True)
    async def bumpreminder_autolock(self, ctx: Context, choice: str) -> None:
        if ctx.guild.id not in self._cache:
            self._cache[ctx.guild.id] = {}
        enabled = choice.lower() in ("on", "true", "enable", "1")
        self._cache[ctx.guild.id]["autolock"] = enabled
        await ctx.success(f"Autolock {'enabled' if enabled else 'disabled'}.")

    @bumpreminder.command(
        name="message",
        description="Set the reminder message to run /bump",
        guild_only=True,
    )
    @describe(message="The reminder message to send")
    @has_permissions(manage_channels=True)
    async def bumpreminder_message(self, ctx: Context, *, message: str) -> None:
        if ctx.guild.id not in self._cache:
            self._cache[ctx.guild.id] = {}
        self._cache[ctx.guild.id]["remind_message"] = message
        await ctx.success(f"Reminder message set to: {message}")
async def setup(bot: Vain):
    await bot.add_cog(BumpReminder(bot))
