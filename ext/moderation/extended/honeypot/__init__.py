from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import Any, Iterable

import discord
from discord import ui
from discord.ext import commands
from discord.ext.commands import group

from core.discord.package import Package
from core.discord.views.embed import panel_embed
from core.managers.permissions import has_permissions

_VALID_PUNISHMENTS = ("kick", "ban", "softban", "timeout")
_DEFAULT_PUNISHMENTS = ["ban"]
_TIMEOUT_SECONDS = 7 * 24 * 60 * 60  # 7 days
_MISSING: Any = object()


def _normalize_punishments(raw: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        value = str(item or "").strip().lower()
        if value in {"hardban", "hard"}:
            value = "ban"
        if value not in _VALID_PUNISHMENTS or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out or list(_DEFAULT_PUNISHMENTS)


def _punishment_phrase(punishments: list[str]) -> str:
    labels = [f"**{p}**" for p in punishments]
    if not labels:
        labels = ["**ban**"]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _trap_body() -> str:
    """Minimal trap copy — no accent, no counters in the text body."""
    return "\n".join(
        [
            "### Do not send messages here",
            "",
            "-# This channel is a trap for compromised accounts.",
            "-# Anything posted here is removed and the account is banned.",
        ]
    )


class Honeypot(Package):
    """Honeypot channel trap for compromised / malicious accounts."""

    async def _ensure_table(self) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        with contextlib.suppress(Exception):
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS honeypot (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT,
                    message_id BIGINT,
                    alert_channel_id BIGINT,
                    punishments TEXT[] NOT NULL DEFAULT ARRAY['ban']::TEXT[],
                    caught INT NOT NULL DEFAULT 0,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )

    async def _get_row(self, guild_id: int) -> dict | None:
        await self._ensure_table()
        if getattr(self.db, "pool", None) is None:
            return None
        row = await self.db.fetchrow(
            "SELECT * FROM honeypot WHERE guild_id = $1",
            guild_id,
        )
        return dict(row) if row else None

    async def _upsert(
        self,
        guild_id: int,
        *,
        channel_id: int | None = _MISSING,
        message_id: int | None = _MISSING,
        alert_channel_id: int | None = _MISSING,
        punishments: list[str] | None = None,
        caught: int | None = None,
        enabled: bool | None = None,
    ) -> dict:
        await self._ensure_table()
        current = await self._get_row(guild_id) or {
            "guild_id": guild_id,
            "channel_id": None,
            "message_id": None,
            "alert_channel_id": None,
            "punishments": list(_DEFAULT_PUNISHMENTS),
            "caught": 0,
            "enabled": False,
        }

        next_channel = (
            current.get("channel_id") if channel_id is _MISSING else channel_id
        )
        next_message = (
            current.get("message_id") if message_id is _MISSING else message_id
        )
        next_alert = (
            current.get("alert_channel_id")
            if alert_channel_id is _MISSING
            else alert_channel_id
        )
        next_punishments = (
            _normalize_punishments(current.get("punishments"))
            if punishments is None
            else _normalize_punishments(punishments)
        )
        next_caught = int(current.get("caught") or 0) if caught is None else int(caught)
        next_enabled = bool(current.get("enabled")) if enabled is None else bool(enabled)

        await self.db.execute(
            """
            INSERT INTO honeypot (
                guild_id, channel_id, message_id, alert_channel_id,
                punishments, caught, enabled
            )
            VALUES ($1, $2, $3, $4, $5::TEXT[], $6, $7)
            ON CONFLICT (guild_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                message_id = EXCLUDED.message_id,
                alert_channel_id = EXCLUDED.alert_channel_id,
                punishments = EXCLUDED.punishments,
                caught = EXCLUDED.caught,
                enabled = EXCLUDED.enabled
            """,
            guild_id,
            next_channel,
            next_message,
            next_alert,
            next_punishments,
            next_caught,
            next_enabled,
        )
        return {
            "guild_id": guild_id,
            "channel_id": next_channel,
            "message_id": next_message,
            "alert_channel_id": next_alert,
            "punishments": next_punishments,
            "caught": next_caught,
            "enabled": next_enabled,
        }

    def _trap_layout(self, caught: int) -> ui.LayoutView:
        """Minimal colorless trap card with a non-clickable Caught counter."""
        layout = ui.LayoutView(timeout=None)
        container = ui.Container()
        container.add_item(ui.TextDisplay(_trap_body()))
        container.add_item(ui.Separator(visible=True))

        row = ui.ActionRow()
        row.add_item(
            ui.Button(
                style=discord.ButtonStyle.secondary,
                label=f"Caught: {int(caught)}",
                emoji="🍯",
                disabled=True,
            )
        )
        container.add_item(row)
        layout.add_item(container)
        return layout

    async def _post_trap_message(
        self,
        channel: discord.TextChannel,
        caught: int,
    ) -> discord.Message:
        return await channel.send(view=self._trap_layout(caught))

    async def _refresh_trap_message(
        self,
        guild: discord.Guild,
        row: dict,
    ) -> None:
        channel_id = row.get("channel_id")
        message_id = row.get("message_id")
        if not channel_id or not message_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        caught = int(row.get("caught") or 0)
        layout = self._trap_layout(caught)
        with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=layout)
            return
        # Trap message missing — repost and store the new id.
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            msg = await self._post_trap_message(channel, caught)
            await self._upsert(guild.id, message_id=msg.id)

    def _is_exempt(self, member: discord.Member) -> bool:
        if member.bot:
            return True
        if member.guild.owner_id == member.id:
            return True
        perms = member.guild_permissions
        return bool(perms.administrator or perms.manage_guild or perms.ban_members)

    async def _apply_punishments(
        self,
        member: discord.Member,
        punishments: list[str],
        *,
        reason: str,
    ) -> list[str]:
        applied: list[str] = []
        for action in punishments:
            try:
                if action == "kick":
                    await member.kick(reason=reason)
                    applied.append("kick")
                    break  # member gone
                if action == "ban":
                    await member.ban(delete_message_seconds=0, reason=reason)
                    applied.append("ban")
                    break
                if action == "softban":
                    await member.ban(delete_message_seconds=86400, reason=reason)
                    await member.guild.unban(
                        discord.Object(id=member.id),
                        reason=f"{reason} (softban unban)",
                    )
                    applied.append("softban")
                    break
                if action == "timeout":
                    until = discord.utils.utcnow() + timedelta(seconds=_TIMEOUT_SECONDS)
                    await member.timeout(until, reason=reason)
                    applied.append("timeout")
            except (discord.Forbidden, discord.HTTPException):
                continue
        return applied

    async def _send_alert(
        self,
        guild: discord.Guild,
        row: dict,
        member: discord.Member,
        applied: list[str],
        *,
        content: str = "",
        attachment_count: int = 0,
        channel_label: str = "`?`",
    ) -> None:
        alert_id = row.get("alert_channel_id")
        if not alert_id:
            return
        channel = guild.get_channel(int(alert_id))
        if not isinstance(channel, discord.TextChannel):
            return
        phrase = _punishment_phrase(applied or _normalize_punishments(row.get("punishments")))
        preview = (content or "")[:180] + ("…" if len(content or "") > 180 else "")
        if not preview and attachment_count:
            preview = f"[{attachment_count} attachment(s)]"
        if not preview:
            preview = "*empty / non-text message*"

        embed = panel_embed(
            color=None,
            title="Honeypot Triggered",
            lines=[
                f"**Member**: {member.mention} (`{member.id}`)",
                f"**Action**: {phrase}",
                f"**Channel**: {channel_label}",
                f"**Message**: {preview}",
            ],
            footer=f"Accounts caught: {int(row.get('caught') or 0)}",
            timestamp=True,
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await channel.send(embed=embed)

    @group(
        name="honeypot",
        aliases=["hp", "honeypots"],
        description="Protect your server against malicious intent.",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def honeypot(self, ctx):
        """Protect your server against malicious intent."""
        return await ctx.send_help(ctx.command)

    @honeypot.command(
        name="setup",
        aliases=["set", "configure"],
        description="Create the honeypot channel and arm the trap.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_setup(self, ctx):
        """Create the honeypot channel and arm the trap."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id)
        if row and row.get("enabled") and row.get("channel_id"):
            existing = ctx.guild.get_channel(int(row["channel_id"]))
            if isinstance(existing, discord.TextChannel):
                return await ctx.warn(
                    f"Honeypot is already armed in {existing.mention} — "
                    f"use `{ctx.clean_prefix}honeypot disable` first"
                )

        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await ctx.warn("I need **Manage Channels** to create the honeypot")

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                add_reactions=False,
            ),
            me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                manage_channels=True,
                read_message_history=True,
            ),
        }

        try:
            channel = await ctx.guild.create_text_channel(
                name="honeypot",
                overwrites=overwrites,
                topic="Do not send messages here — trap channel for compromised accounts.",
                reason=f"Honeypot setup by {ctx.author} ({ctx.author.id})",
                position=len(ctx.guild.channels),
            )
        except discord.Forbidden:
            return await ctx.warn("I couldn't create the honeypot channel")
        except discord.HTTPException:
            return await ctx.fail("Discord rejected the honeypot channel creation")

        punishments = _normalize_punishments(row.get("punishments") if row else None)
        caught = int(row.get("caught") or 0) if row else 0

        try:
            msg = await self._post_trap_message(channel, caught)
        except (discord.Forbidden, discord.HTTPException):
            with contextlib.suppress(discord.HTTPException):
                await channel.delete(reason="Honeypot setup failed to post trap message")
            return await ctx.fail("Couldn't post the honeypot trap message")

        await self._upsert(
            ctx.guild.id,
            channel_id=channel.id,
            message_id=msg.id,
            punishments=punishments,
            caught=caught,
            enabled=True,
        )
        return await ctx.success(f"Honeypot armed in {channel.mention}")

    @honeypot.command(
        name="disable",
        aliases=["remove", "delete", "unset"],
        description="Disable the honeypot and remove its channel.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_disable(self, ctx):
        """Disable the honeypot and remove its channel."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id)
        if not row or not row.get("enabled"):
            return await ctx.warn("Honeypot is not currently **enabled**")

        channel_id = row.get("channel_id")
        channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await channel.delete(
                    reason=f"Honeypot disabled by {ctx.author} ({ctx.author.id})"
                )

        await self._upsert(
            ctx.guild.id,
            channel_id=None,
            message_id=None,
            enabled=False,
        )
        return await ctx.success("Honeypot has been **disabled** and the channel removed")

    @honeypot.command(
        name="alerts",
        aliases=["alert", "log", "logs"],
        description="Set or clear the alert channel for honeypot triggers.",
        example=",honeypot alerts #mod-logs",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_alerts(self, ctx, *, channel: str | None = None):
        """Set or clear the alert channel for honeypot triggers."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id) or {}
        raw = (channel or "").strip()

        if not raw:
            current_id = row.get("alert_channel_id")
            if current_id:
                current = ctx.guild.get_channel(int(current_id))
                label = current.mention if current else f"`{current_id}`"
                return await ctx.send(
                    embed=panel_embed(
                        color=None,
                        title="Honeypot Alerts",
                        lines=[
                            f"**Alert channel**: {label}",
                            f"-# Use `{ctx.clean_prefix}honeypot alerts #channel` to change",
                            f"-# Use `{ctx.clean_prefix}honeypot alerts clear` to remove",
                        ],
                        timestamp=False,
                    )
                )
            return await ctx.warn(
                f"No alert channel set — use `{ctx.clean_prefix}honeypot alerts #channel`"
            )

        if raw.lower() in {"clear", "none", "off", "remove", "reset", "unset", "disable"}:
            if not row.get("alert_channel_id"):
                return await ctx.warn("No honeypot **alert channel** is set")
            await self._upsert(ctx.guild.id, alert_channel_id=None)
            return await ctx.success("Honeypot alert channel has been **cleared**")

        try:
            target = await commands.TextChannelConverter().convert(ctx, raw)
        except Exception:
            return await ctx.warn(f"Couldn't find a text channel matching `{raw}`")

        await self._upsert(ctx.guild.id, alert_channel_id=target.id)
        return await ctx.success(f"Honeypot alerts will post in {target.mention}")

    @honeypot.command(
        name="punishment",
        aliases=["action", "punish"],
        description="Set the punishment(s). Choose one or more of: kick, ban, softban, timeout.",
        example=",honeypot punishment softban",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_punishment(self, ctx, *, actions: str | None = None):
        """Set the punishment(s). Choose one or more of: kick, ban, softban, timeout."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id) or {}
        if not actions or not str(actions).strip():
            current = _normalize_punishments(row.get("punishments"))
            return await ctx.send(
                embed=panel_embed(
                    color=None,
                    title="Honeypot Punishment",
                    lines=[
                        f"**Current**: {_punishment_phrase(current)}",
                        "-# Options: `kick`, `ban`, `softban`, `timeout`",
                        f"-# Example: `{ctx.clean_prefix}honeypot punishment ban timeout`",
                    ],
                    timestamp=False,
                )
            )

        tokens = [
            tok.strip().lower()
            for tok in actions.replace(",", " ").replace("|", " ").split()
            if tok.strip()
        ]
        if any(tok in {"clear", "reset", "default"} for tok in tokens):
            tokens = list(_DEFAULT_PUNISHMENTS)

        invalid = [
            t
            for t in tokens
            if t not in _VALID_PUNISHMENTS and t not in {"hardban", "hard"}
        ]
        if invalid:
            return await ctx.warn(
                f"Invalid punishment(s): {', '.join(f'`{t}`' for t in invalid)} — "
                f"use `kick`, `ban`, `softban`, or `timeout`"
            )

        punishments = _normalize_punishments(tokens)
        updated = await self._upsert(ctx.guild.id, punishments=punishments)

        # Live-edit the trap card so the punishment text stays accurate.
        if updated.get("enabled"):
            await self._refresh_trap_message(ctx.guild, updated)

        return await ctx.success(
            f"Honeypot punishment set to {_punishment_phrase(punishments)}"
        )

    @honeypot.command(
        name="settings",
        aliases=["setting", "view", "show"],
        description="View the current honeypot configuration.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_settings(self, ctx):
        """View the current honeypot configuration."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id)
        if not row:
            return await ctx.warn(
                f"Honeypot is not configured — use `{ctx.clean_prefix}honeypot setup`"
            )

        channel = (
            ctx.guild.get_channel(int(row["channel_id"]))
            if row.get("channel_id")
            else None
        )
        alert = (
            ctx.guild.get_channel(int(row["alert_channel_id"]))
            if row.get("alert_channel_id")
            else None
        )
        punishments = _normalize_punishments(row.get("punishments"))
        status = "**armed**" if row.get("enabled") and channel else "**disabled**"

        embed = panel_embed(
            color=None,
            title="Honeypot Settings",
            lines=[
                f"**Status**: {status}",
                f"**Channel**: {channel.mention if channel else '`none`'}",
                f"**Alerts**: {alert.mention if alert else '`none`'}",
                f"**Punishment**: {_punishment_phrase(punishments)}",
                f"**Accounts Caught**: **{int(row.get('caught') or 0)}**",
            ],
            footer="honeypot · compromised account trap",
            timestamp=False,
        )
        return await ctx.send(embed=embed)

    @Package.listener("on_message")
    async def on_honeypot_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return
        if getattr(self.db, "pool", None) is None:
            return

        row = await self._get_row(message.guild.id)
        if not row or not row.get("enabled") or not row.get("channel_id"):
            return
        if int(message.channel.id) != int(row["channel_id"]):
            return
        # Ignore the trap message itself / staff.
        if message.id == row.get("message_id"):
            return
        if self._is_exempt(message.author):
            return

        # Snapshot message details before delete (for optional alert channel).
        reason = f"Honeypot triggered in #{getattr(message.channel, 'name', 'honeypot')}"
        author = message.author
        content = message.content or ""
        attachment_count = len(message.attachments or [])
        channel_mention = getattr(message.channel, "mention", None) or f"`{message.channel.id}`"

        # Immediate delete — never surface errors to the channel.
        with contextlib.suppress(discord.Forbidden, discord.HTTPException, discord.NotFound):
            await message.delete()

        # Default action is ban; configured punishments still apply, silently.
        punishments = _normalize_punishments(row.get("punishments"))
        if "ban" not in punishments and "softban" not in punishments and "kick" not in punishments:
            punishments = ["ban", *punishments]

        applied = await self._apply_punishments(author, punishments, reason=reason)

        caught = int(row.get("caught") or 0) + 1
        updated = await self._upsert(message.guild.id, caught=caught)
        await self._refresh_trap_message(message.guild, updated)

        await self._send_alert(
            message.guild,
            updated,
            author,
            applied,
            content=content,
            attachment_count=attachment_count,
            channel_label=channel_mention,
        )
