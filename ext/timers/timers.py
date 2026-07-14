from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import TYPE_CHECKING, Optional

import discord
from core.discord.package import Package, tasks

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.values import color
from core.tools.aesthetic import aesthetic_embed, panel_embed

if TYPE_CHECKING:
    from core.vain import Vain


def parse_duration(text: str) -> Optional[int]:
    total = 0
    current = ""
    for char in text.lower():
        if char.isdigit():
            current += char
        elif char in "smhdw":
            if not current:
                return None
            value = int(current)
            if char == "s":
                total += value
            elif char == "m":
                total += value * 60
            elif char == "h":
                total += value * 3600
            elif char == "d":
                total += value * 86400
            elif char == "w":
                total += value * 604800
            current = ""
    if current:
        total += int(current)
    return total if total > 0 else None


class Timers(Package):
    """Timed events, reminders, and scheduled tasks."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._timers: dict[str, dict] = {}
        self._loop_running = False

    async def cog_load(self):
        self._timer_loop.start()

    async def cog_unload(self):
        self._timer_loop.stop()
        for timer in self._timers.values():
            timer.get("task", None)

    @tasks.loop(seconds=5)
    async def _timer_loop(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        to_remove = []
        for timer_id, data in list(self._timers.items()):
            if data["expires"] <= now:
                to_remove.append(timer_id)
                try:
                    user = self.bot.get_user(data["user_id"])
                    if user:
                        embed = panel_embed(
                            title="⏰ Reminder",
                            color=color.base,
                            lines=[data["text"]],
                            timestamp=False,
                        )
                        embed.add_field(name="Set", value=discord.utils.format_dt(data["created"], style="R"), inline=True)
                        await user.send(embed=embed)
                except Exception:
                    pass

        for tid in to_remove:
            self._timers.pop(tid, None)

    @group(
        name="timer",
        description="Create and manage timed reminders",
        invoke_without_command=True,
        aliases=["reminder", "schedule"],
    )
    async def timer(self, ctx: Context, duration: str = None, *, text: str = None) -> None:
        if not duration or not text:
            await ctx.send_help(ctx.command)
            return

        seconds = parse_duration(duration)
        if not seconds:
            await ctx.fail(f"Invalid duration format. Use e.g. `10m`, `2h`, `1d`.")
            return

        if seconds > 7 * 86400:
            await ctx.warn("Timer cannot exceed 7 days.")
            return

        timer_id = uuid.uuid4().hex[:8]
        expires = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
        self._timers[timer_id] = {
            "user_id": ctx.author.id,
            "channel_id": ctx.channel.id,
            "guild_id": ctx.guild.id,
            "text": text,
            "created": discord.utils.utcnow(),
            "expires": expires,
        }

        embed = panel_embed(
            title="⏰ Timer Set",
            color=color.base,
            lines=[f"I'll remind you in **{self._format_remaining(seconds)}**."],
            timestamp=False,
        )
        embed.add_field(name="ID", value=f"`{timer_id}`", inline=True)
        embed.add_field(name="Expires", value=discord.utils.format_dt(expires, style="R"), inline=True)
        embed.add_field(name="Message", value=text, inline=False)
        await ctx.send(embed=embed)

    @timer.command(
        name="list",
        description="View all your active timers",
        aliases=["all"],
    )
    async def timer_list(self, ctx: Context) -> None:
        user_timers = {k: v for k, v in self._timers.items() if v["user_id"] == ctx.author.id}
        if not user_timers:
            await ctx.warn("You have no active timers.")
            return

        entries = []
        for tid, data in sorted(user_timers.items(), key=lambda x: x[1]["expires"]):
            remaining = (data["expires"] - discord.utils.utcnow()).total_seconds()
            remaining_str = self._format_remaining(max(0, int(remaining)))
            entries.append(f"`{tid}` — **{data['text'][:40]}** — expires {remaining_str}")

        embed = panel_embed(
            title=f"Active Timers ({len(user_timers)})",
            color=color.base,
            lines=entries,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @timer.command(
        name="cancel",
        description="Cancel an active timer",
        aliases=["remove", "delete", "del"],
    )
    @describe(timer_id="The ID of the timer to cancel")
    async def timer_cancel(self, ctx: Context, timer_id: str) -> None:
        data = self._timers.get(timer_id)
        if not data or data["user_id"] != ctx.author.id:
            await ctx.fail(f"No timer found with ID `{timer_id}`.")
            return
        self._timers.pop(timer_id, None)
        await ctx.success(f"Cancelled timer `{timer_id}`.")

    @timer.command(
        name="clear",
        description="Clear all your active timers",
    )
    async def timer_clear(self, ctx: Context) -> None:
        to_remove = [k for k, v in self._timers.items() if v["user_id"] == ctx.author.id]
        if not to_remove:
            await ctx.warn("You have no active timers.")
            return

        for tid in to_remove:
            self._timers.pop(tid, None)
        await ctx.success(f"Cleared **{len(to_remove)}** timers.")

    def _format_remaining(self, seconds: int) -> str:
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, sec = divmod(seconds, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if sec:
            parts.append(f"{sec}s")
        return " ".join(parts)


async def setup(bot: Vain):
    await bot.add_cog(Timers(bot))
