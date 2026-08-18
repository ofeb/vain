from __future__ import annotations

import contextlib
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands, ui
from discord.ext import tasks

from core.discord.package import Package
from core.discord.hybrid import hybrid
from core.discord.views.embed import c2
from core.tools.moderation_args import parse_duration_seconds, is_duration_token


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class _RemindDurationModal(ui.Modal, title="Remind me"):
    duration = ui.TextInput(
        label="When?",
        placeholder="e.g. 30m, 2h, 1d",
        min_length=1,
        max_length=32,
        required=True,
    )

    def __init__(self, cog: "Remind", message: discord.Message):
        super().__init__()
        self.cog = cog
        self.target_message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        seconds = parse_duration_seconds(str(self.duration.value).strip())
        if not seconds or seconds < 30:
            return await interaction.followup.send(
                "Please provide a **valid duration** (minimum 30 seconds, e.g. `30m`, `2h`, `1d`).",
                ephemeral=True,
            )
        if seconds > 30 * 86400:
            return await interaction.followup.send(
                "Reminders can't exceed **30 days**.",
                ephemeral=True,
            )
        text = (self.target_message.content or "").strip()
        if not text:
            text = f"[message]({self.target_message.jump_url})"
        else:
            if len(text) > 900:
                text = text[:897].rstrip() + "..."
            text = f"{text}\n-# [jump]({self.target_message.jump_url})"

        when = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=seconds)
        guild_id = interaction.guild.id if interaction.guild else 0
        channel_id = interaction.channel.id if interaction.channel else 0
        rid = await self.cog.db.fetchval(
            """INSERT INTO reminders (user_id, guild_id, channel_id, message, time)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            interaction.user.id,
            guild_id,
            channel_id,
            text,
            when,
        )
        pretty = self.cog._format_duration(seconds)
        await interaction.followup.send(
            f"I'll remind you in **{pretty}**\n> -# **id:** #{rid}",
            ephemeral=True,
        )


class Remind(Package):
    """Personal reminders stored in the database."""

    def __init__(self, bot):
        super().__init__(bot)
        self._menus: list[app_commands.ContextMenu] = []

    async def cog_load(self) -> None:
        self._register_menus()
        if not self._remind_loop.is_running():
            self._remind_loop.start()
        await super().cog_load()

    async def cog_unload(self) -> None:
        for menu in self._menus:
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(menu.name, type=discord.AppCommandType.message)
        self._menus.clear()
        if self._remind_loop.is_running():
            self._remind_loop.cancel()
        await super().cog_unload()

    def _register_menus(self) -> None:
        for menu in list(self._menus):
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(menu.name, type=discord.AppCommandType.message)
        self._menus.clear()

        menu = app_commands.ContextMenu(
            name="Remind me to do this",
            callback=self.ctx_remind,
            type=discord.AppCommandType.message,
        )
        with contextlib.suppress(Exception):
            app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(menu)
        with contextlib.suppress(Exception):
            app_commands.allowed_installs(guilds=True, users=True)(menu)
        try:
            self.bot.tree.add_command(menu, override=True)
            self._menus.append(menu)
        except Exception:
            pass

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

    async def ctx_remind(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Message context menu: Remind me to do this."""
        await interaction.response.send_modal(_RemindDurationModal(self, message))

    @hybrid(
        name="remind",
        aliases=["reminder", "remindme"],
        description="Set a personal reminder",
        group=True,
        example=",remind 2h check tickets",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    async def remind(self, ctx, *, reminder: str = None):
        """Set a reminder. Format: <duration> <message>"""
        if not reminder or not str(reminder).strip():
            return await ctx.send_help(ctx.command)

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
                "Please provide a **valid duration**\n"
                f"> -# **minimum:** 30 seconds (e.g. `30m`, `2h`, `1d`)"
            )
        if seconds > 30 * 86400:
            return await ctx.warn(
                "Reminders can't exceed **30 days**\n"
                f"> -# **maximum:** 30 days"
            )

        message = " ".join(message_tokens).strip()
        if not message:
            return await ctx.warn(
                "Please provide a **reminder message**\n"
                f"> -# **usage:** {ctx.cmd('remind 2h check tickets')}"
            )

        when = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=seconds)
        guild_id = ctx.guild.id if ctx.guild else 0
        channel_id = ctx.channel.id if ctx.channel else 0

        rid = await self.db.fetchval(
            """INSERT INTO reminders (user_id, guild_id, channel_id, message, time)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            ctx.author.id,
            guild_id,
            channel_id,
            message,
            when,
        )

        pretty = self._format_duration(seconds)
        return await ctx.success(
            f"I'll remind you in **{pretty}**\n"
            f"> -# **message:** {message}\n"
            f"> -# **id:** #{rid}"
        )

    @remind.command(
        name="list",
        aliases=["ls", "all"],
        description="List your active reminders",
        example=",remind list",
    )
    async def remind_list(self, ctx):
        """List your pending reminders."""
        rows = await self.db.fetch(
            """SELECT id, message, time
               FROM reminders
               WHERE user_id = $1
               ORDER BY time ASC
               LIMIT 25""",
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn("You have **no active reminders**")

        lines = []
        for row in rows:
            ts = row["time"]
            if isinstance(ts, datetime) and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            stamp = int(ts.timestamp()) if isinstance(ts, datetime) else 0
            msg = (row["message"] or "").strip()
            if len(msg) > 80:
                msg = msg[:77] + "..."
            lines.append(f"**#{row['id']}** · <t:{stamp}:R>\n> -# {msg}")

        embed = c2(
            title="Your reminders",
            message="\n".join(lines),
            footer=f"{len(rows)} reminder{'s' if len(rows) != 1 else ''}",
        )
        return await ctx.send(embed=embed)

    @remind.command(
        name="remove",
        aliases=["rm", "delete", "del", "cancel"],
        description="Remove a reminder by id",
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
            return await ctx.warn(
                f"Reminder **#{id}** not found\n"
                f"> -# **check your reminders with:** {ctx.cmd('remind list')}"
            )
        return await ctx.success(
            f"Removed reminder\n"
            f"> -# **id:** #{id}"
        )

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

                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    msg = (row["message"] or "").strip() or "—"
                    embed = c2(
                        title="Reminder",
                        message=(
                            f"**It's time!**\n"
                            f"> -# **message:** {msg}\n"
                            f"> -# **id:** #{row['id']}"
                        ),
                        footer="you set this earlier",
                        timestamp=True,
                    )
                    await user.send(content=user.mention, embed=embed)
            except Exception:
                continue

    @_remind_loop.before_loop
    async def _before_remind_loop(self) -> None:
        await self.bot.wait_until_ready()
