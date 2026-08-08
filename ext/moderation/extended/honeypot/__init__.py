from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import Any, Iterable

import discord
from discord import ui
from discord.ext import commands
from discord.ext.commands import BucketType, cooldown, group

from config import color
from core.discord.package import Package
from core.discord.views.embed import panel_embed
from core.managers.permissions import has_permissions
from core.tools.embed import is_container_script, is_embed_script, maybe_wrap_embed_script, parse

_VALID_PUNISHMENTS = ("kick", "ban", "softban", "timeout")
_DEFAULT_PUNISHMENTS = ["ban"]
_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
_MISSING: Any = object()
_DEFAULT_TRAP_SCRIPT = (
    "{container}"
    "$v{description: :warning: DO NOT SEND MESSAGES HERE! :warning:}"
    "$v{separator: divider: true && spacing: 1}"
    "$v{button: label: Caught: {honeypot.caught} && style: yellow}"
)


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


def _comma(value: Any) -> str:
    """Format a number with thousands separators (human-friendly)."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _trap_body() -> str:
    """Minimal trap copy - no accent, no counters in the text body."""
    return ":warning: DO NOT SEND MESSAGES HERE! :warning:"


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
                    enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    embed_script TEXT
                )
                """
            )
        
        with contextlib.suppress(Exception):
            await self.db.execute(
                "ALTER TABLE honeypot ADD COLUMN IF NOT EXISTS embed_script TEXT"
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
        embed_script: str | None = _MISSING,
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
            "embed_script": None,
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
        next_script = (
            current.get("embed_script") if embed_script is _MISSING else embed_script
        )

        await self.db.execute(
            """
            INSERT INTO honeypot (
                guild_id, channel_id, message_id, alert_channel_id,
                punishments, caught, enabled, embed_script
            )
            VALUES ($1, $2, $3, $4, $5::TEXT[], $6, $7, $8)
            ON CONFLICT (guild_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                message_id = EXCLUDED.message_id,
                alert_channel_id = EXCLUDED.alert_channel_id,
                punishments = EXCLUDED.punishments,
                caught = EXCLUDED.caught,
                enabled = EXCLUDED.enabled,
                embed_script = EXCLUDED.embed_script
            """,
            guild_id,
            next_channel,
            next_message,
            next_alert,
            next_punishments,
            next_caught,
            next_enabled,
            next_script,
        )
        return {
            "guild_id": guild_id,
            "channel_id": next_channel,
            "message_id": next_message,
            "alert_channel_id": next_alert,
            "punishments": next_punishments,
            "caught": next_caught,
            "enabled": next_enabled,
            "embed_script": next_script,
        }

    def _default_trap_layout(self, caught: int) -> ui.LayoutView:
        """Default trap card with a non-clickable Caught counter."""
        layout = ui.LayoutView(timeout=None)
        container = ui.Container(accent_colour=color.warn)
        container.add_item(ui.TextDisplay(_trap_body()))
        container.add_item(ui.Separator(visible=True))

        row = ui.ActionRow()
        row.add_item(
            ui.Button(
                style=discord.ButtonStyle.premium,
                label=f"Caught: {_comma(caught)}",
                disabled=True,
            )
        )
        container.add_item(row)
        layout.add_item(container)
        return layout

    def _honeypot_kwargs(self, guild: discord.Guild, row: dict) -> dict[str, Any]:
        channel = None
        channel_id = row.get("channel_id")
        if channel_id:
            channel = guild.get_channel(int(channel_id))
        punishments = _normalize_punishments(row.get("punishments"))
        return {
            "guild": guild,
            "channel": channel,
            "honeypot": {
                "caught": int(row.get("caught") or 0),
                "caught_count": int(row.get("caught") or 0),
                "channel": channel,
                "channel_id": channel_id,
                "channel_name": getattr(channel, "name", "") if channel else "",
                "channel_mention": getattr(channel, "mention", "") if channel else "",
                "punishments": punishments,
                "punishment": _punishment_phrase(punishments),
            },
        }

    async def _build_trap_payload(
        self,
        guild: discord.Guild,
        row: dict,
    ) -> dict[str, Any]:
        """Build send/edit kwargs for the trap message (script or default layout)."""
        script = (row.get("embed_script") or "").strip()
        caught = int(row.get("caught") or 0)
        if not script:
            return {"view": self._default_trap_layout(caught), "embed": None, "content": None}

        try:
            bot = getattr(self, "bot", None)
            if bot is not None and hasattr(bot, "create_embed"):
                prepared = await bot.create_embed(
                    script,
                    **self._honeypot_kwargs(guild, row),
                )
                data = dict(getattr(prepared, "data", None) or {})
            else:
                
                from core.tools.embed import Script

                s = Script(script)
                data = await s.data(True, **self._honeypot_kwargs(guild, row))
        except Exception:
            return {"view": self._default_trap_layout(caught), "embed": None, "content": None}

        
        view = data.get("view")
        if view is not None:
            for child in list(getattr(view, "children", []) or []):
                self._disable_buttons_recursive(child)
            
            walk = list(getattr(view, "children", []) or [])
            while walk:
                item = walk.pop(0)
                self._disable_buttons_recursive(item)
                kids = getattr(item, "children", None) or getattr(item, "items", None)
                if kids:
                    walk.extend(list(kids))

        payload: dict[str, Any] = {}
        if data.get("content") is not None:
            payload["content"] = data["content"]
        else:
            payload["content"] = None
        if data.get("embed") is not None:
            payload["embed"] = data["embed"]
        else:
            payload["embed"] = None
        if data.get("embeds"):
            payload["embeds"] = data["embeds"]
        if view is not None:
            payload["view"] = view
        if not payload.get("view") and not payload.get("embed") and not payload.get("content"):
            return {"view": self._default_trap_layout(caught), "embed": None, "content": None}
        return payload

    @staticmethod
    def _disable_buttons_recursive(item: Any) -> None:
        if isinstance(item, (discord.ui.Button, ui.Button)):
            try:
                item.disabled = True
            except Exception:
                pass

    async def _post_trap_message(
        self,
        channel: discord.TextChannel,
        caught: int,
        row: dict | None = None,
    ) -> discord.Message:
        guild = channel.guild
        base_row = dict(row or {})
        base_row.setdefault("caught", caught)
        base_row.setdefault("channel_id", channel.id)
        payload = await self._build_trap_payload(guild, base_row)
        return await channel.send(**payload)

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
        payload = await self._build_trap_payload(guild, row)
        with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = await channel.fetch_message(int(message_id))
            await message.edit(**payload)
            return

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            msg = await self._post_trap_message(
                channel, int(row.get("caught") or 0), row=row
            )
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
                    break  
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
            footer=f"Accounts caught: {_comma(row.get('caught'))}",
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
    @cooldown(1, 10, BucketType.guild)
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
                    f"Honeypot is already armed in {existing.mention} - "
                    f"use `{ctx.clean_prefix}honeypot disable` to turn it off"
                )

        
        if row and row.get("channel_id") and not row.get("enabled"):
            existing = ctx.guild.get_channel(int(row["channel_id"]))
            if isinstance(existing, discord.TextChannel):
                punishments = _normalize_punishments(row.get("punishments"))
                caught = int(row.get("caught") or 0)
                setup_row = {
                    "channel_id": existing.id,
                    "caught": caught,
                    "punishments": punishments,
                    "embed_script": row.get("embed_script"),
                }
                try:
                    msg = await self._post_trap_message(
                        existing, caught, row=setup_row
                    )
                except (discord.Forbidden, discord.HTTPException):
                    return await ctx.fail("Couldn't post the honeypot trap message")
                await self._upsert(
                    ctx.guild.id,
                    channel_id=existing.id,
                    message_id=msg.id,
                    punishments=punishments,
                    caught=caught,
                    enabled=True,
                    embed_script=setup_row.get("embed_script"),
                )
                return await ctx.success(
                    f"Honeypot re-armed in {existing.mention} - previous configuration kept"
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
                topic="Auto configured honeypot channel for compromised accounts.",
                reason=f"Honeypot setup by {ctx.author} ({ctx.author.id})",
                position=len(ctx.guild.channels),
            )
        except discord.Forbidden:
            return await ctx.warn("I couldn't create the honeypot channel")
        except discord.HTTPException:
            return await ctx.fail("Discord rejected the honeypot channel creation")

        punishments = _normalize_punishments(row.get("punishments") if row else None)
        caught = int(row.get("caught") or 0) if row else 0

        setup_row = {
            "channel_id": channel.id,
            "caught": caught,
            "punishments": punishments,
            "embed_script": (row or {}).get("embed_script") if row else None,
        }
        try:
            msg = await self._post_trap_message(channel, caught, row=setup_row)
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
            embed_script=setup_row.get("embed_script"),
        )
        return await ctx.success(f"Honeypot armed in {channel.mention}")

    @honeypot.command(
        name="disable",
        aliases=["off", "disarm"],
        description="Disable the honeypot without deleting configuration or the trap channel.",
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 10, BucketType.guild)
    async def honeypot_disable(self, ctx):
        """Disable the honeypot without deleting configuration or the trap channel."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id)
        if not row:
            return await ctx.warn("Honeypot is not configured for this server")
        if not row.get("enabled"):
            return await ctx.warn(
                f"Honeypot is already **disabled** - "
                f"use `{ctx.clean_prefix}honeypot setup` to arm it again"
            )

        await self._upsert(ctx.guild.id, enabled=False)
        return await ctx.success(
            "Honeypot **disabled** - configuration and channel kept. "
            f"Use `{ctx.clean_prefix}honeypot reset` to delete everything"
        )

    @honeypot.command(
        name="reset",
        aliases=["remove", "delete", "unset", "clear"],
        description="Delete honeypot configuration and remove its channel. This cannot be undone.",
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 10, BucketType.guild)
    async def honeypot_reset(self, ctx):
        """Delete honeypot configuration and remove its channel. This cannot be undone."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id)
        if not row:
            return await ctx.warn("Honeypot is not configured for this server")

        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** honeypot settings and delete the trap channel? "
            "This action **cannot be undone**."
        )
        if not ok:
            return await ctx.warn("Honeypot reset **cancelled**")

        channel_id = row.get("channel_id")
        channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await channel.delete(
                    reason=f"Honeypot reset by {ctx.author} ({ctx.author.id})"
                )

        await self.db.execute(
            "DELETE FROM honeypot WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success(
            "Honeypot configuration **deleted**. This action cannot be undone."
        )

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
                f"No alert channel set - use `{ctx.clean_prefix}honeypot alerts #channel`"
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
                f"Invalid punishment(s): {', '.join(f'`{t}`' for t in invalid)} - "
                f"use `kick`, `ban`, `softban`, or `timeout`"
            )

        punishments = _normalize_punishments(tokens)
        updated = await self._upsert(ctx.guild.id, punishments=punishments)

        
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
                f"Honeypot is not configured - use `{ctx.clean_prefix}honeypot setup`"
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
        script = (row.get("embed_script") or "").strip()
        script_label = "custom" if script else "default"

        embed = panel_embed(
            color=None,
            title="Honeypot Settings",
            lines=[
                f"**Status**: {status}",
                f"**Channel**: {channel.mention if channel else '`none`'}",
                f"**Alerts**: {alert.mention if alert else '`none`'}",
                f"**Punishment**: {_punishment_phrase(punishments)}",
                f"**Accounts Caught**: **{_comma(row.get('caught'))}**",
                f"**Trap embed**: `{script_label}`",
            ],
            footer="honeypot · compromised account trap",
            timestamp=False,
        )
        return await ctx.send(embed=embed)

    @honeypot.command(
        name="embed",
        aliases=["message", "script", "trap"],
        description="Set a custom embed/container script for the honeypot trap message.",
        example=",honeypot embed {container}$v{description: Do not post here}",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_embed(self, ctx, *, script: str | None = None):
        """Customize the trap message with an embed or container script."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await self._get_row(ctx.guild.id) or {}
        raw = (script or "").strip()

        if not raw:
            current = (row.get("embed_script") or "").strip()
            if not current:
                return await ctx.send(
                    embed=panel_embed(
                        color=None,
                        title="Honeypot Embed",
                        lines=[
                            "**Trap embed**: `default`",
                            f"-# Use `{ctx.clean_prefix}honeypot embed <script>` to customize",
                            f"-# Use `{ctx.clean_prefix}honeypot embed clear` to reset",
                            f"-# Variables: `{ctx.clean_prefix}variables honeypot`",
                        ],
                        timestamp=False,
                    )
                )
            preview = current if len(current) <= 900 else current[:900] + "…"
            return await ctx.send(
                embed=panel_embed(
                    color=None,
                    title="Honeypot Embed",
                    lines=[
                        "**Trap embed**: `custom`",
                        f"```\n{preview}\n```",
                        f"-# Use `{ctx.clean_prefix}honeypot embed clear` to reset",
                        f"-# Variables: `{ctx.clean_prefix}variables honeypot`",
                    ],
                    timestamp=False,
                )
            )

        if raw.lower() in {"clear", "none", "off", "reset", "default", "remove"}:
            updated = await self._upsert(ctx.guild.id, embed_script=None)
            if updated.get("enabled"):
                await self._refresh_trap_message(ctx.guild, updated)
            return await ctx.success("Honeypot trap embed reset to **default**")

        
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("ts") or raw.lower().startswith("txt"):
                raw = raw.split("\n", 1)[-1]
            raw = raw.strip()

        if not (is_embed_script(raw) or is_container_script(raw) or raw.startswith(("{", "$v"))):
            raw = maybe_wrap_embed_script(raw)

        
        try:
            test_row = {
                **row,
                "embed_script": raw,
                "caught": int(row.get("caught") or 0),
                "channel_id": row.get("channel_id"),
            }
            payload = await self._build_trap_payload(ctx.guild, test_row)
            if not payload:
                return await ctx.fail("Couldn't parse that trap script")
        except Exception as exc:
            return await ctx.fail(f"Invalid trap script: {exc}")

        updated = await self._upsert(ctx.guild.id, embed_script=raw)
        if updated.get("enabled"):
            await self._refresh_trap_message(ctx.guild, updated)
        return await ctx.success(
            f"Honeypot trap embed updated - see `{ctx.clean_prefix}variables honeypot` for vars"
        )

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
        
        if message.id == row.get("message_id"):
            return
        if self._is_exempt(message.author):
            return

        
        reason = f"Honeypot triggered in #{getattr(message.channel, 'name', 'honeypot')}"
        author = message.author
        content = message.content or ""
        attachment_count = len(message.attachments or [])
        channel_mention = getattr(message.channel, "mention", None) or f"`{message.channel.id}`"

        
        with contextlib.suppress(discord.Forbidden, discord.HTTPException, discord.NotFound):
            await message.delete()

        
        punishments = _normalize_punishments(row.get("punishments"))
        if "ban" not in punishments and "softban" not in punishments and "kick" not in punishments:
            punishments = ["ban", *punishments]

        applied = await self._apply_punishments(author, punishments, reason=reason)

        
        if not applied:
            await self._send_alert(
                message.guild,
                row,
                author,
                applied,
                content=content,
                attachment_count=attachment_count,
                channel_label=channel_mention,
            )
            return

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
