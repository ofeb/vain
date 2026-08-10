from __future__ import annotations

import contextlib
from datetime import datetime, timezone

import discord
from discord.ext import tasks
from discord.ext.commands import group

from core.discord.package import Package
from core.tools.moderation_args import parse_duration_seconds, is_duration_token
from core.discord.views.embed import panel_embed, reply_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class Remind(Package):
    """Personal reminders stored in the database."""

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_load(self) -> None:
        if not self._remind_loop.is_running():
            self._remind_loop.start()
        await super().cog_load()

    async def cog_unload(self) -> None:
        if self._remind_loop.is_running():
            self._remind_loop.cancel()
        await super().cog_unload()

    def _format_duration(self, seconds: int) -> str:
        units = (
            ("week", 604800),
            ("day", 86400),
            ("hour", 3600),
            ("minute", 60),
            ("second", 1),
        )
        parts: list[str] = []
        remainder = max(0, int(seconds))
        for label, chunk in units:
            if remainder < chunk:
                continue
            count, remainder = divmod(remainder, chunk)
            parts.append(f"{count} {label}{'s' if count != 1 else ''}")
            if len(parts) == 2:
                break
        return ", ".join(parts) if parts else "0 seconds"

    @group(
        name="remind",
        aliases=["reminder", "remindme"],
        description="Set a personal reminder",
        invoke_without_command=True,
        example=",remind 2h check tickets",
    )
    async def remind(self, ctx, *, reminder: str):
        """Set a reminder. Format: <duration> <message>"""
        tokens = reminder.split()
        if not tokens:
            return await ctx.send_help(ctx.command)

        seconds = None
        message_tokens = list(tokens)
        if is_duration_token(tokens[0]):
            seconds = parse_duration_seconds(tokens[0])
            message_tokens = tokens[1:]
        elif len(tokens) >= 2 and is_duration_token(tokens[-1]):
            seconds = parse_duration_seconds(tokens[-1])
            message_tokens = tokens[:-1]

        if not seconds or seconds < 30:
            return await ctx.warn(
                "Provide a duration of at least **30 seconds** (e.g. `30m`, `2h`, `1d`)"
            )
        if seconds > 30 * 86400:
            return await ctx.warn("Reminders cannot exceed **30 days**")

        message = " ".join(message_tokens).strip()
        if not message:
            return await ctx.warn("Provide a reminder message")

        when = datetime.now(timezone.utc).replace(tzinfo=None) + discord.utils.utcnow().__class__.resolution  # type: ignore
        
        from datetime import timedelta

        when = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=seconds)

        row = await self.db.fetchrow(
            """INSERT INTO reminders (user_id, guild_id, message, time)
               VALUES ($1, $2, $3, $4)
               RETURNING id""",
            ctx.author.id,
            ctx.guild.id if ctx.guild else 0,
            message[:1500],
            when,
        )
        rid = row["id"] if row else "?"
        label = self._format_duration(seconds)
        return await ctx.success(
            f"Reminder **#{rid}** set for **{label}**\n-# **{message[:200]}**"
        )

    @remind.command(
        name="list",
        aliases=["ls", "all"],
        description="View your active reminders",
    )
    async def remind_list(self, ctx):
        """List your reminders."""
        rows = await self.db.fetch(
            """SELECT id, message, time
               FROM reminders
               WHERE user_id = $1
               ORDER BY time ASC""",
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn("You have **no active reminders**")

        lines = []
        for row in rows[:25]:
            when = row["time"]
            stamp = discord.utils.format_dt(when, style="R") if when else "unknown"
            msg = (row["message"] or "")[:80]
            lines.append(label_line(f"#{row['id']}", f"{msg} - {stamp}"))

        embed = panel_embed(
            title=f"Your Reminders ({len(rows)})",
            color=None,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @remind.command(
        name="remove",
        aliases=["delete", "del", "cancel"],
        description="Remove one of your reminders",
        example=",remind remove 12",
    )
    async def remind_remove(self, ctx, id: int):
        """Remove a reminder by id."""
        result = await self.db.execute(
            "DELETE FROM reminders WHERE id = $1 AND user_id = $2",
            id,
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"Reminder **#{id}** not found")
        return await ctx.success(f"Removed reminder **#{id}**")

    @tasks.loop(seconds=20.0)
    async def _remind_loop(self) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            rows = await self.db.fetch(
                """SELECT id, user_id, guild_id, message, time
                   FROM reminders
                   WHERE time <= $1
                   ORDER BY time ASC
                   LIMIT 50""",
                now,
            )
        except Exception:
            return

        for row in rows:
            try:
                await self.db.execute("DELETE FROM reminders WHERE id = $1", row["id"])
                user = self.bot.get_user(row["user_id"])
                if user is None:
                    with contextlib.suppress(Exception):
                        user = await self.bot.fetch_user(row["user_id"])
                if user is None:
                    continue
                embed = reply_embed(
                    color=None,
                    message=f"**Reminder**\n{row['message']}",
                )
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await user.send(embed=embed)
            except Exception:
                continue

    @_remind_loop.before_loop
    async def _before_remind_loop(self) -> None:
        await self.bot.wait_until_ready()
