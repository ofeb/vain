from __future__ import annotations

import contextlib
import datetime
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands
from discord.ext.commands import BucketType, cooldown

from core.discord.package import Package, tasks
from core.discord.ctx import Context
from core.discord.hybrid import describe, group
from core.discord.views.embed import c2, panel_embed
from core.managers.permissions import has_permissions
from core.tools.embed import Script, is_container_script, is_embed_script, maybe_wrap_embed_script
from config import color

from .events import BumpReminderEvents
from .proper.constants import (
    BUMP_COOLDOWN,
    DEFAULT_REMINDER_SCRIPT,
    DEFAULT_THANKYOU_SCRIPT,
)
from .settings import Settings

if TYPE_CHECKING:
    from core.vain import Vain


def _fmt_dt(value: Any) -> str:
    if not value:
        return "`never`"
    if isinstance(value, str):
        return value
    try:
        return discord.utils.format_dt(value, style="R")
    except Exception:
        return str(value)


class BumpReminder(BumpReminderEvents, Package):
    """Remind guild members to promote the guild on Disboard."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._reminder_sent: set[int] = set()

    async def cog_load(self) -> None:
        await Settings.ensure_table(self.bot)
        if not self._bump_watcher.is_running():
            self._bump_watcher.start()

    async def cog_unload(self) -> None:
        if self._bump_watcher.is_running():
            self._bump_watcher.cancel()

    # ------------------------------------------------------------------
    # Script send helper
    # ------------------------------------------------------------------

    def _bumper_kwargs(
        self,
        guild: discord.Guild,
        *,
        bumper: discord.abc.User | discord.Member | None,
        settings: Settings | None = None,
        next_bump_at: datetime.datetime | None = None,
        last_bump_at: datetime.datetime | None = None,
        channel: discord.abc.GuildChannel | None = None,
    ) -> dict[str, Any]:
        role = settings.role if settings else None
        kw: dict[str, Any] = {
            "guild": guild,
            "channel": channel or (settings.channel if settings else None),
            "role": role,
            "bumper": bumper,
            "user": bumper,  # user.* aliases work too
            "member": bumper,
        }
        if next_bump_at is not None:
            kw["next_bump_at"] = next_bump_at
        if last_bump_at is not None:
            kw["last_bump_at"] = last_bump_at
        if settings is not None:
            kw["bump"] = {
                "role": role,
                "channel": settings.channel,
                "next": next_bump_at or settings.next_bump_at,
                "last": last_bump_at or settings.last_bump_at,
            }
        return kw

    async def _send_bump_script(
        self,
        dest: discord.abc.Messageable,
        script: str,
        *,
        guild: discord.Guild,
        bumper: discord.abc.User | discord.Member | None = None,
        settings: Settings | None = None,
        next_bump_at: datetime.datetime | None = None,
        last_bump_at: datetime.datetime | None = None,
        content_prefix: str | None = None,
        ping_role: bool = False,
    ) -> discord.Message | None:
        raw = (script or "").strip() or DEFAULT_REMINDER_SCRIPT
        if not (
            is_embed_script(raw)
            or is_container_script(raw)
            or raw.startswith(("{", "$v"))
        ):
            # plain text still goes through Script for variable expansion
            pass
        else:
            raw = maybe_wrap_embed_script(raw)

        channel = dest if isinstance(dest, (discord.TextChannel, discord.Thread)) else None
        kwargs = self._bumper_kwargs(
            guild,
            bumper=bumper,
            settings=settings,
            next_bump_at=next_bump_at,
            last_bump_at=last_bump_at,
            channel=channel,  # type: ignore[arg-type]
        )

        # Role ping only when explicitly requested (reminder path), not thank-you
        role_mention = ""
        if content_prefix is not None:
            role_mention = content_prefix
        elif ping_role and settings and settings.role:
            role_mention = settings.role.mention

        payload: dict[str, Any] | None = None
        try:
            payload = await Script(raw, bumper).data(True, **kwargs)
        except Exception:
            # Fallback plain container
            with contextlib.suppress(Exception):
                payload = await Script(DEFAULT_REMINDER_SCRIPT, bumper).data(
                    True, **kwargs
                )
            if not payload:
                text = raw[:2000]
                if role_mention:
                    text = f"{role_mention}\n{text}"
                return await dest.send(content=text)

        # Merge role ping into content when not already present
        if role_mention:
            existing = payload.get("content") or ""
            if role_mention not in existing:
                payload["content"] = (
                    f"{role_mention}\n{existing}".strip() if existing else role_mention
                )

        # Drop empty color-less noise keys
        for k in list(payload.keys()):
            if payload[k] is None:
                payload.pop(k, None)

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            return await dest.send(**payload)
        return None

    # ------------------------------------------------------------------
    # Watcher — fires reminders when next_bump_at is due
    # ------------------------------------------------------------------

    @tasks.loop(seconds=45)
    async def _bump_watcher(self) -> None:
        if getattr(self.bot.db, "pool", None) is None:
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            rows = await Settings.fetch_all_enabled(self.bot)
        except Exception:
            return

        for row in rows:
            guild_id = int(row.get("guild_id") or 0)
            if not guild_id:
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue

            next_at = row.get("next_bump_at")
            if next_at is None:
                continue
            if getattr(next_at, "tzinfo", None) is None:
                next_at = next_at.replace(tzinfo=datetime.timezone.utc)

            if now < next_at:
                # clear sent flag once we're back in cooldown window after a send
                self._reminder_sent.discard(guild_id)
                continue

            # Already reminded for this window?
            if guild_id in self._reminder_sent:
                continue

            channel_id = row.get("channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                continue

            settings = Settings(self.bot, guild, row)
            bumper = None
            bumper_id = row.get("last_bumper_id")
            if bumper_id:
                bumper = guild.get_member(int(bumper_id)) or self.bot.get_user(
                    int(bumper_id)
                )

            script = (settings.message or "").strip() or DEFAULT_REMINDER_SCRIPT
            sent = await self._send_bump_script(
                channel,
                script,
                guild=guild,
                bumper=bumper,
                settings=settings,
                next_bump_at=next_at,
                last_bump_at=row.get("last_bump_at"),
                ping_role=True,
            )
            if sent is not None:
                self._reminder_sent.add(guild_id)
                # Push next window so we don't spam; real bump will reschedule precisely
                with contextlib.suppress(Exception):
                    await settings.upsert(
                        next_bump_at=now + datetime.timedelta(seconds=BUMP_COOLDOWN)
                    )

    @_bump_watcher.before_loop
    async def _before_watcher(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @group(
        name="bumpreminder",
        aliases=["bumpremind", "bumpr"],
        description="Remind your guild members to promote the guild on Disboard.",
        guild_only=True,
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def bumpreminder(self, ctx: Context):
        """Remind your guild members to promote the guild on Disboard."""
        await ctx.send_help(ctx.command)

    @bumpreminder.command(
        name="enable",
        aliases=["setup", "on"],
        description="Enable bump reminders for this guild.",
        guild_only=True,
        example=",bumpreminder enable #bump",
    )
    @describe(channel="Channel where reminders are posted")
    @has_permissions(manage_guild=True)
    @cooldown(1, 5, BucketType.guild)
    async def bumpreminder_enable(
        self,
        ctx: Context,
        channel: discord.TextChannel | None = None,
    ):
        """Enable bump reminders for this guild."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        if getattr(self.bot.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        target = channel or (
            ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        )
        if target is None:
            return await ctx.warn("Provide a text channel for reminders")

        settings = await Settings.fetch(self.bot, ctx.guild)
        now = discord.utils.utcnow()
        # If never bumped, schedule a reminder soon so setup is useful
        next_at = settings.next_bump_at
        if next_at is None:
            next_at = now + datetime.timedelta(minutes=1)

        await settings.upsert(
            channel_id=target.id,
            enabled=True,
            next_bump_at=next_at,
        )
        self._reminder_sent.discard(ctx.guild.id)

        embed = c2(
            color=color.base,
            title="Bump Reminder",
            message=(
                f"**Enabled** in {target.mention}\n"
                f"-# Reminders fire after a successful Disboard `/bump` (every 2 hours)\n"
                f"-# Customize with `{ctx.clean_prefix}bumpreminder message` · "
                f"`{ctx.clean_prefix}bumpreminder thankyou` · "
                f"`{ctx.clean_prefix}bumpreminder role`"
            ),
            timestamp=False,
        )
        return await ctx.send(embed=embed)

    @bumpreminder.command(
        name="disable",
        aliases=["remove", "reset"],
        description="Disable bump reminders and delete the configuration.",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 5, BucketType.guild)
    async def bumpreminder_disable(self, ctx: Context):
        """Disable bump reminders and delete the configuration."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        if getattr(self.bot.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        settings = await Settings.fetch(self.bot, ctx.guild)
        if not await Settings.exists(self.bot, ctx.guild):
            return await ctx.warn("Bump reminder is not configured")

        await settings.delete()
        self._reminder_sent.discard(ctx.guild.id)
        return await ctx.success("Bump reminders **disabled** and configuration deleted")

    @bumpreminder.command(
        name="toggle",
        description="Toggle bump reminders on or off.",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def bumpreminder_toggle(self, ctx: Context):
        """Toggle bump reminders on or off."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        if getattr(self.bot.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings.channel_id:
            return await ctx.warn(
                f"Set a channel first with `{ctx.clean_prefix}bumpreminder enable #channel`"
            )

        new_state = not settings.enabled
        await settings.upsert(enabled=new_state)
        if new_state:
            self._reminder_sent.discard(ctx.guild.id)
        return await ctx.success(
            f"Bump reminders are now **{'enabled' if new_state else 'disabled'}**"
        )

    @bumpreminder.command(
        name="message",
        aliases=["reminder", "remindmessage"],
        description="Set the reminder message sent when it's time to bump.",
        guild_only=True,
        usage="(script or text)",
        example=",bumpreminder message {container}$v{description: Time to /bump}",
    )
    @describe(script="Plain text or embed/container script")
    @has_permissions(manage_guild=True)
    async def bumpreminder_message(
        self,
        ctx: Context,
        *,
        script: str | None = None,
    ):
        """Set the reminder message sent when it's time to bump."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        settings = await Settings.fetch(self.bot, ctx.guild)
        raw = (script or "").strip()

        if not raw:
            current = (settings.message or "").strip() or DEFAULT_REMINDER_SCRIPT
            preview = current if len(current) <= 900 else current[:900] + "…"
            return await ctx.send(
                embed=panel_embed(
                    color=color.base,
                    title="Bump Reminder Message",
                    lines=[
                        f"```\n{preview}\n```",
                        f"-# Clear with `{ctx.clean_prefix}bumpreminder message clear`",
                        f"-# Vars: `{ctx.clean_prefix}variables bumper`",
                    ],
                    timestamp=False,
                )
            )

        if raw.lower() in {"clear", "reset", "default", "none"}:
            await settings.upsert(message=None)
            return await ctx.success("Reminder message reset to the **default** script")

        if raw.startswith("```") and raw.endswith("```"):
            raw = raw.strip("`")
            if "\n" in raw:
                raw = raw.split("\n", 1)[-1]
            raw = raw.strip()

        await settings.upsert(message=raw)
        # Live preview
        with contextlib.suppress(Exception):
            await self._send_bump_script(
                ctx.channel,
                raw,
                guild=ctx.guild,
                bumper=ctx.author,
                settings=settings,
            )
        return await ctx.success("Bump reminder message **updated**")

    @bumpreminder.command(
        name="thankyou",
        aliases=["thanks", "thankmessage"],
        description="Set the thank-you message sent after a successful bump.",
        guild_only=True,
        usage="(script or text)",
        example=",bumpreminder thankyou Thanks {bumper.mention}!",
    )
    @describe(script="Plain text or embed/container script")
    @has_permissions(manage_guild=True)
    async def bumpreminder_thankyou(
        self,
        ctx: Context,
        *,
        script: str | None = None,
    ):
        """Set the thank-you message sent after a successful bump."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        settings = await Settings.fetch(self.bot, ctx.guild)
        raw = (script or "").strip()

        if not raw:
            current = (settings.thankyou_message or "").strip() or DEFAULT_THANKYOU_SCRIPT
            preview = current if len(current) <= 900 else current[:900] + "…"
            return await ctx.send(
                embed=panel_embed(
                    color=color.base,
                    title="Bump Thank-You Message",
                    lines=[
                        f"```\n{preview}\n```",
                        f"-# Clear with `{ctx.clean_prefix}bumpreminder thankyou clear`",
                        f"-# Vars: `{ctx.clean_prefix}variables bumper`",
                    ],
                    timestamp=False,
                )
            )

        if raw.lower() in {"clear", "reset", "default", "none"}:
            await settings.upsert(thankyou_message=None)
            return await ctx.success("Thank-you message reset to the **default** script")

        if raw.startswith("```") and raw.endswith("```"):
            raw = raw.strip("`")
            if "\n" in raw:
                raw = raw.split("\n", 1)[-1]
            raw = raw.strip()

        await settings.upsert(thankyou_message=raw)
        with contextlib.suppress(Exception):
            await self._send_bump_script(
                ctx.channel,
                raw,
                guild=ctx.guild,
                bumper=ctx.author,
                settings=settings,
            )
        return await ctx.success("Bump thank-you message **updated**")

    @bumpreminder.command(
        name="role",
        description="Set (or clear) the role pinged on each reminder.",
        guild_only=True,
        example=",bumpreminder role @Bumpers",
    )
    @describe(role="Role to ping, or clear/none to remove")
    @has_permissions(manage_guild=True)
    async def bumpreminder_role(
        self,
        ctx: Context,
        *,
        role: str | None = None,
    ):
        """Set (or clear) the role pinged on each reminder."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        settings = await Settings.fetch(self.bot, ctx.guild)
        raw = (role or "").strip()

        if not raw:
            current = settings.role
            if current:
                return await ctx.send(
                    embed=panel_embed(
                        color=color.base,
                        title="Bump Reminder Role",
                        lines=[
                            f"**Role**: {current.mention}",
                            f"-# Clear with `{ctx.clean_prefix}bumpreminder role clear`",
                        ],
                        timestamp=False,
                    )
                )
            return await ctx.warn("No reminder role set")

        if raw.lower() in {"clear", "none", "off", "remove", "reset"}:
            await settings.upsert(role_id=None)
            return await ctx.success("Bump reminder role **cleared**")

        try:
            resolved = await commands.RoleConverter().convert(ctx, raw)
        except Exception:
            return await ctx.warn(f"Couldn't find a role matching `{raw}`")

        await settings.upsert(role_id=resolved.id)
        return await ctx.success(f"Bump reminder role set to {resolved.mention}")

    @bumpreminder.command(
        name="settings",
        aliases=["config", "view"],
        description="View the current bump reminder configuration.",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def bumpreminder_settings(self, ctx: Context):
        """View the current bump reminder configuration."""
        if ctx.guild is None:
            return await ctx.warn("Guild only")
        settings = await Settings.fetch(self.bot, ctx.guild)

        ch = settings.channel
        role = settings.role
        status = "**enabled**" if settings.enabled and ch else "**disabled**"
        msg = "custom" if (settings.message or "").strip() else "default"
        ty = "custom" if (settings.thankyou_message or "").strip() else "default"
        bumper_label = "`—`"
        if settings.last_bumper_id:
            m = ctx.guild.get_member(int(settings.last_bumper_id))
            bumper_label = m.mention if m else f"`{settings.last_bumper_id}`"

        embed = panel_embed(
            color=color.base,
            title="Bump Reminder Settings",
            lines=[
                f"**Status**: {status}",
                f"**Channel**: {ch.mention if ch else '`none`'}",
                f"**Role**: {role.mention if role else '`none`'}",
                f"**Reminder message**: `{msg}`",
                f"**Thank-you message**: `{ty}`",
                f"**Last bump**: {_fmt_dt(settings.last_bump_at)}",
                f"**Next reminder**: {_fmt_dt(settings.next_bump_at)}",
                f"**Last bumper**: {bumper_label}",
            ],
            footer="Disboard · /bump every 2 hours",
            timestamp=False,
        )
        return await ctx.send(embed=embed)


async def setup(bot: Vain):
    await bot.add_cog(BumpReminder(bot))
