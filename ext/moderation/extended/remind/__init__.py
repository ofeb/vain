from __future__ import annotations

import contextlib
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands, ui
from discord.ext import tasks

from core.discord.package import Package
from core.discord.hybrid import hybrid
from core.discord.views.embed import c2
from core.tools.moderation_args import parse_duration_seconds, is_duration_token


_JUMP_RE = re.compile(r"\n?-#\s*\[jump\]\([^)]+\)\s*$", re.IGNORECASE)


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
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        try:
            await self.cog._ensure_schema()
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
            text = (self.target_message.content or "").strip() or "Reminder"
            if len(text) > 900:
                text = text[:897].rstrip() + "..."
            jump = self.target_message.jump_url
            guild_id = interaction.guild.id if interaction.guild else 0
            rid, pretty = await self.cog._create_reminder(
                user_id=interaction.user.id,
                guild_id=guild_id,
                message=text,
                seconds=seconds,
                jump_url=jump,
            )
            await interaction.followup.send(
                f"I'll remind you in **{pretty}**\n> -# **id:** #{rid}",
                ephemeral=True,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await interaction.followup.send(
                    f"Couldn't save that reminder\n> -# {exc}",
                    ephemeral=True,
                )


class Remind(Package):
    """Personal reminders stored in the database. Always delivered via DM."""

    def __init__(self, bot):
        super().__init__(bot)
        self._menus: list[app_commands.ContextMenu] = []

    async def cog_load(self) -> None:
        await self._ensure_schema()
        self._register_menus()
        if not self._remind_loop.is_running():
            self._remind_loop.start()
        with contextlib.suppress(Exception):
            self._force_reminder_contexts()
        await super().cog_load()

    def _force_reminder_contexts(self) -> None:
        """Ensure /reminder is on the tree and installable in guilds, DMs, and group DMs."""
        from discord import app_commands as _ac
        cmd = getattr(self, "reminder", None)
        if cmd is None:
            return
        app = getattr(cmd, "app_command", None)
        if app is not None:
            with contextlib.suppress(Exception):
                app = _ac.allowed_contexts(guilds=True, dms=True, private_channels=True)(app)
                app = _ac.allowed_installs(guilds=True, users=True)(app)
                try:
                    cmd.app_command = app
                except Exception:
                    object.__setattr__(cmd, "app_command", app)
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(app.name)
            with contextlib.suppress(Exception):
                self.bot.tree.add_command(app)
        for child in list(getattr(cmd, "commands", []) or []):
            capp = getattr(child, "app_command", None)
            if capp is None:
                continue
            with contextlib.suppress(Exception):
                capp = _ac.allowed_contexts(guilds=True, dms=True, private_channels=True)(capp)
                capp = _ac.allowed_installs(guilds=True, users=True)(capp)

    async def cog_unload(self) -> None:
        for menu in self._menus:
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(menu.name, type=discord.AppCommandType.message)
        self._menus.clear()
        if self._remind_loop.is_running():
            self._remind_loop.cancel()
        await super().cog_unload()

    async def _ensure_schema(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                guild_id BIGINT NOT NULL DEFAULT 0,
                number INTEGER NOT NULL DEFAULT 1,
                message TEXT NOT NULL,
                jump_url TEXT,
                time TIMESTAMP WITHOUT TIME ZONE NOT NULL
            )
            """
        )
        for stmt in (
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS guild_id BIGINT NOT NULL DEFAULT 0",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS message TEXT",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS time TIMESTAMP WITHOUT TIME ZONE",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS user_id BIGINT",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS number INTEGER",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS jump_url TEXT",
        ):
            with contextlib.suppress(Exception):
                await self.db.execute(stmt)
        
        with contextlib.suppress(Exception):
            await self.db.execute(
                """
                UPDATE reminders r
                SET number = sub.n
                FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY time ASC, id ASC) AS n
                    FROM reminders
                    WHERE number IS NULL OR number < 1
                ) sub
                WHERE r.id = sub.id
                """
            )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS reminders_user_idx ON reminders (user_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS reminders_time_idx ON reminders (time)"
        )

    async def _next_number(self, user_id: int) -> int:
        """Smallest free positive integer for this user (restarts at 1 when empty)."""
        rows = await self.db.fetch(
            "SELECT number FROM reminders WHERE user_id = $1 AND number IS NOT NULL",
            user_id,
        )
        used = {int(r["number"]) for r in rows if r["number"] is not None}
        n = 1
        while n in used:
            n += 1
        return n

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
        with contextlib.suppress(Exception):
            self.bot.tree.add_command(menu, override=True)
            self._menus.append(menu)

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
        await interaction.response.send_modal(_RemindDurationModal(self, message))

    async def _create_reminder(
        self,
        *,
        user_id: int,
        guild_id: int,
        message: str,
        seconds: int,
        jump_url: str | None = None,
    ) -> tuple[int, str]:
        await self._ensure_schema()
        number = await self._next_number(user_id)
        when = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=seconds)
        await self.db.fetchval(
            """INSERT INTO reminders (user_id, guild_id, number, message, jump_url, time)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id""",
            user_id,
            guild_id,
            number,
            message,
            jump_url,
            when,
        )
        return number, self._format_duration(seconds)

    def _parse_reminder_args(self, reminder: str) -> tuple[int | None, str | None, str | None]:
        tokens = (reminder or "").split()
        if not tokens:
            return None, None, "empty"
        seconds = None
        message_tokens = list(tokens)
        if is_duration_token(tokens[0]):
            seconds = parse_duration_seconds(tokens[0])
            message_tokens = tokens[1:]
        elif len(tokens) >= 2 and is_duration_token(tokens[-1]):
            seconds = parse_duration_seconds(tokens[-1])
            message_tokens = tokens[:-1]
        if not seconds or seconds < 30:
            return None, None, "duration"
        if seconds > 30 * 86400:
            return None, None, "max"
        message = " ".join(message_tokens).strip()
        if not message:
            return None, None, "message"
        return seconds, message, None

    @hybrid(
        name="reminder",
        aliases=["remind", "remindme"],
        description="set a personal reminder",
        group=True,
        invoke_without_command=True,
        example=",reminder add 2h check tickets",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    async def reminder(self, ctx):
        if ctx.invoked_subcommand is not None:
            return
        return await ctx.send_help(ctx.command)

    @reminder.command(
        name="add",
        aliases=["set", "create", "new"],
        description="add a personal reminder",
        example=",reminder add 2h check tickets",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @app_commands.describe(
        chore="what to be reminded about",
        in_="when (e.g. 30s, 5m, 5h, 1d)",
    )
    @app_commands.rename(in_="in")
    async def reminder_add(self, ctx, chore: str = None, in_: str = None):
        await self._ensure_schema()

        seconds = None
        message = None

        if getattr(ctx, "interaction", None) is not None:
            if not chore or not str(chore).strip():
                return await ctx.warn(
                    "Provide a **chore** to be reminded about\n"
                    f"> -# **usage:** /reminder add chore:… in:30m"
                )
            if not in_ or not str(in_).strip():
                return await ctx.warn(
                    "Provide **when** to remind you\n"
                    f"> -# **examples:** `30s`, `5m`, `5h`, `1d`"
                )
            seconds = parse_duration_seconds(str(in_).strip())
            message = str(chore).strip()
            if not seconds or seconds < 30:
                return await ctx.warn(
                    "Please provide a **valid duration**\n"
                    f"> -# **minimum:** 30 seconds (e.g. `30m`, `2h`, `1d`)"
                )
            if seconds > 30 * 86400:
                return await ctx.warn(
                    "Reminders can't exceed **30 days**\n> -# **maximum:** 30 days"
                )
        else:
            rest = self._prefix_rest(ctx)
            if not rest:
                if chore or in_:
                    rest = " ".join(x for x in (chore, in_) if x).strip()
            if not rest:
                return await ctx.warn(
                    "Provide a duration and message\n"
                    f"> -# **usage:** {ctx.cmd('reminder add 2h check tickets')}"
                )
            seconds, message, err = self._parse_reminder_args(rest)
            if err == "duration":
                return await ctx.warn(
                    "Please provide a **valid duration**\n"
                    f"> -# **minimum:** 30 seconds (e.g. `30m`, `2h`, `1d`)"
                )
            if err == "max":
                return await ctx.warn(
                    "Reminders can't exceed **30 days**\n> -# **maximum:** 30 days"
                )
            if err == "message" or not message:
                return await ctx.warn(
                    "Please provide a **reminder message**\n"
                    f"> -# **usage:** {ctx.cmd('reminder add 2h check tickets')}"
                )
            if err or not seconds:
                return await ctx.send_help(ctx.command)

        if not message or not seconds:
            return await ctx.warn(
                "Provide a **chore** and **when**\n"
                f"> -# **usage:** {ctx.cmd('reminder add 2h check tickets')}"
            )

        
        try:
            dm = ctx.author.dm_channel
            if dm is None:
                dm = await ctx.author.create_dm()
        except (discord.Forbidden, discord.HTTPException):
            return await ctx.warn(
                "I **can't DM you**\n"
                "> -# open your DMs with this bot, then try again"
            )

        guild_id = ctx.guild.id if ctx.guild else 0
        try:
            jump = getattr(getattr(ctx, "message", None), "jump_url", None)
            rid, pretty = await self._create_reminder(
                user_id=ctx.author.id,
                guild_id=guild_id,
                message=message,
                seconds=seconds,
                jump_url=jump,
            )
        except Exception as exc:
            return await ctx.fail(f"Couldn't save that reminder\n> -# {exc}")

        return await ctx.success(
            f"I'll remind you in **{pretty}**\n"
            f"> -# **chore:** {message}\n"
            f"> -# **id:** #{rid}"
        )

    def _prefix_rest(self, ctx) -> str:
        """Remaining text after the invoked command path (prefix only)."""
        msg = getattr(ctx, "message", None)
        if msg is None or not getattr(msg, "content", None):
            return ""
        content = msg.content
        inv = (ctx.invoked_with or "").lower()
        if not inv:
            return ""
        low = content.lower()
        idx = low.find(inv)
        if idx < 0:
            return ""
        rest = content[idx + len(inv) :].strip()
        
        
        
        
        parent = getattr(ctx, "command", None)
        if parent is not None and getattr(parent, "parent", None) is not None:
            
            return rest
        
        return rest

    @reminder.command(
        name="list",
        aliases=["ls", "all"],
        description="list your active reminders",
        example=",reminder list",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    async def reminder_list(self, ctx):
        await self._ensure_schema()
        rows = await self.db.fetch(
            """SELECT number, message, jump_url, time
               FROM reminders
               WHERE user_id = $1
               ORDER BY number ASC
               LIMIT 25""",
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn("You have **no active reminders**")

        blocks: list[str] = []
        for row in rows:
            ts = row["time"]
            if isinstance(ts, datetime) and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            stamp = int(ts.timestamp()) if isinstance(ts, datetime) else 0
            msg = (row["message"] or "").strip()
            msg = _JUMP_RE.sub("", msg).strip()
            if len(msg) > 120:
                msg = msg[:117] + "..."
            num = row["number"] if row["number"] is not None else "?"
            jump = (row["jump_url"] or "").strip()
            line = f"**#{num}** · <t:{stamp}:R>\n{msg}"
            if jump:
                line += f"\n[jump to message]({jump})"
            blocks.append(line)

        embed = c2(
            title="Your reminders",
            message="\n\n".join(blocks),
            footer=f"{len(rows)} reminder{'s' if len(rows) != 1 else ''}",
        )
        return await ctx.send(embed=embed)

    @reminder.command(
        name="remove",
        aliases=["rm", "delete", "del", "cancel"],
        description="remove a reminder by id",
        example=",reminder remove 1",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    async def reminder_remove(self, ctx, id: int):
        await self._ensure_schema()
        result = await self.db.execute(
            "DELETE FROM reminders WHERE number = $1 AND user_id = $2",
            id,
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"Reminder **#{id}** not found\n"
                f"> -# **check your reminders with:** {ctx.cmd('reminder list')}"
            )
        return await ctx.success(f"Removed reminder\n> -# **id:** #{id}")

    @tasks.loop(seconds=5.0)
    async def _remind_loop(self) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            rows = await self.db.fetch(
                """SELECT id, user_id, number, message, jump_url, time
                   FROM reminders
                   WHERE time <= $1
                   ORDER BY time ASC, id ASC
                   LIMIT 100""",
                now,
            )
        except Exception:
            return

        if not rows:
            return

        for row in rows:
            try:
                user = self.bot.get_user(row["user_id"])
                if user is None:
                    with contextlib.suppress(Exception):
                        user = await self.bot.fetch_user(row["user_id"])
                if user is None:
                    
                    with contextlib.suppress(Exception):
                        await self.db.execute(
                            "DELETE FROM reminders WHERE id = $1", row["id"]
                        )
                    continue

                delivered = await self._deliver_reminder(user, row)
                if delivered:
                    with contextlib.suppress(Exception):
                        await self.db.execute(
                            "DELETE FROM reminders WHERE id = $1", row["id"]
                        )
                
            except Exception:
                continue

    async def _deliver_reminder(self, user: discord.abc.User, row) -> bool:
        """Send the reminder DM. Returns True if delivered (or permanently undeliverable)."""
        msg = (row["message"] or "").strip() or "something"
        msg = _JUMP_RE.sub("", msg).strip()
        jump = (row.get("jump_url") or "").strip() if hasattr(row, "get") else (row["jump_url"] or "").strip()
        if isinstance(jump, str):
            pass
        else:
            jump = ""

        body = (
            "> **oi wake up**, I'm here to **remind** you to start your **chore**\n\n"
            f"> -# **chore:** {msg}"
        )

        
        try:
            from discord import ui as _ui
            from core.discord.ctx import layout_from_items

            container = _ui.Container()
            for _attr in ("accent_color", "accent_colour", "color", "colour"):
                if hasattr(container, _attr):
                    with contextlib.suppress(Exception):
                        setattr(container, _attr, None)
            container.add_item(_ui.TextDisplay(body))
            items: list = [container]
            if jump.startswith("http"):
                items.append(
                    _ui.ActionRow(
                        _ui.Button(
                            label="When did I say this?",
                            style=discord.ButtonStyle.link,
                            url=jump,
                        )
                    )
                )
            layout = layout_from_items(items, timeout=None)
            await user.send(content=user.mention, view=layout)
            return True
        except discord.Forbidden:
            return True  
        except Exception:
            pass

        try:
            embed = c2(message=body, timestamp=False)
            embed.color = None
            kwargs = {"content": user.mention, "embed": embed}
            if jump.startswith("http"):
                view = discord.ui.View()
                view.add_item(
                    discord.ui.Button(
                        label="When did I say this?",
                        style=discord.ButtonStyle.link,
                        url=jump,
                    )
                )
                kwargs["view"] = view
            await user.send(**kwargs)
            return True
        except discord.Forbidden:
            return True
        except Exception:
            pass

        try:
            text = f"{user.mention}\n{body}"
            if jump.startswith("http"):
                text += f"\n{jump}"
            await user.send(text)
            return True
        except discord.Forbidden:
            return True
        except Exception:
            return False

    @_remind_loop.before_loop
    async def _before_remind_loop(self) -> None:
        await self.bot.wait_until_ready()
