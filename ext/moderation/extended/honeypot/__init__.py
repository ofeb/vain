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
from core.tools.moderation_logs import send_c2_embed
from core.managers.permissions import has_permissions
from core.tools.embed import is_container_script, is_embed_script, maybe_wrap_embed_script

from .models import (
    _DEFAULT_PUNISHMENTS,
    _TIMEOUT_SECONDS,
    _VALID_PUNISHMENTS,
    _comma,
    _normalize_punishments,
    _punishment_phrase,
    _trap_body,
)
from .settings import fetch, remove, upsert


class Honeypot(Package):
    """Honeypot channel trap for compromised / malicious accounts."""

    def _default_trap_layout(
        self, caught: int, punishments: Iterable[str] | None = None
    ) -> ui.LayoutView:
        """Default trap card with a non-clickable Caught counter."""
        layout = ui.LayoutView(timeout=None)
        container = ui.Container(accent_colour=color.warn)
        container.add_item(ui.TextDisplay(_trap_body(punishments)))
        container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.large))

        row = ui.ActionRow()
        row.add_item(
            ui.Button(
                style=discord.ButtonStyle.danger,
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
        punishments = _normalize_punishments(row.get("punishments"))
        if not script:
            return {
                "view": self._default_trap_layout(caught, punishments),
                "embed": None,
                "content": None,
            }

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
            return {
                "view": self._default_trap_layout(caught, punishments),
                "embed": None,
                "content": None,
            }

        
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
            return {
                "view": self._default_trap_layout(caught, punishments),
                "embed": None,
                "content": None,
            }
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
            await upsert(self.bot, guild.id, message_id=msg.id)

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
                if action == "hardban":
                    await member.ban(delete_message_seconds=0, reason=reason)
                    with contextlib.suppress(Exception):
                        await self.db.add_hardban(
                            member.guild.id, member.id,
                            getattr(self.bot.user, "id", 0) or 0,
                            reason,
                        )
                    applied.append("hardban")
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
                    break
                if action == "jail":
                    settings = await self.db.get_server_settings(member.guild.id)
                    jail_role_id = getattr(settings, "jail_role_id", None) if settings else None
                    if jail_role_id:
                        role = member.guild.get_role(int(jail_role_id))
                        if role is not None:
                            await member.add_roles(role, reason=reason)
                            applied.append("jail")
                    break
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
            await send_c2_embed(channel, embed)

    @group(
        name="honeypot",
        aliases=["hp", "honeypots"],
        description="protect your server against malicious intent",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def honeypot(self, ctx):
        """Protect your server against malicious intent."""
        return await ctx.send_help(ctx.command)

    @honeypot.command(
        name="setup",
        aliases=["set", "configure"],
        description="create the honeypot channel and arm the trap",
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 10, BucketType.guild)
    async def honeypot_setup(self, ctx):
        """Create the honeypot channel and arm the trap."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id)
        if row and row.get("enabled") and row.get("channel_id"):
            existing = ctx.guild.get_channel(int(row["channel_id"]))
            if isinstance(existing, discord.TextChannel):
                return await ctx.warn(
                    f"Honeypot is already armed in {existing.mention} - "
                    f"use `{ctx.invoke_prefix}honeypot disable` to turn it off"
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
                await upsert(self.bot,
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

        await upsert(self.bot,
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
        description="disable the honeypot without deleting configuration or the trap channel",
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 10, BucketType.guild)
    async def honeypot_disable(self, ctx):
        """Disable the honeypot without deleting configuration or the trap channel."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id)
        if not row:
            return await ctx.warn("Honeypot is not configured for this server")
        if not row.get("enabled"):
            return await ctx.warn(
                f"Honeypot is already **disabled** - "
                f"use `{ctx.invoke_prefix}honeypot setup` to arm it again"
            )

        await upsert(self.bot, ctx.guild.id, enabled=False)
        return await ctx.success(
            "Honeypot **disabled** - configuration and channel kept. "
            f"Use `{ctx.invoke_prefix}honeypot reset` to delete everything"
        )

    @honeypot.command(
        name="reset",
        aliases=["remove", "delete", "unset", "clear"],
        description="Delete honeypot configuration and remove its channel. This **can't** be undone.",
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 10, BucketType.guild)
    async def honeypot_reset(self, ctx):
        """Delete honeypot configuration and remove its channel. This **can't** be undone."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id)
        if not row:
            return await ctx.warn("Honeypot is not configured for this server")

        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** honeypot settings and delete the trap channel? "
            "This action **can't be undone**."
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

        await remove(self.bot, ctx.guild.id)
        return await ctx.success(
            "Honeypot configuration **deleted**. This action **can't** be undone."
        )

    @honeypot.command(
        name="alerts",
        aliases=["alert", "log", "logs"],
        description="set or clear the alert channel for honeypot triggers",
        example=",honeypot alerts #mod-logs",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_alerts(self, ctx, *, channel: str | None = None):
        """Set or clear the alert channel for honeypot triggers."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id) or {}
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
                            f"> -# Use `{ctx.invoke_prefix}honeypot alerts #channel` to change",
                            f"> -# Use `{ctx.invoke_prefix}honeypot alerts clear` to remove",
                        ],
                        timestamp=False,
                    )
                )
            return await ctx.warn(
                f"No alert channel set - use `{ctx.invoke_prefix}honeypot alerts #channel`"
            )

        if raw.lower() in {"clear", "none", "off", "remove", "reset", "unset", "disable"}:
            if not row.get("alert_channel_id"):
                return await ctx.warn("No honeypot **alert channel** is set")
            await upsert(self.bot, ctx.guild.id, alert_channel_id=None)
            return await ctx.success("Honeypot alert channel has been **cleared**")

        try:
            target = await commands.TextChannelConverter().convert(ctx, raw)
        except Exception:
            return await ctx.warn(f"Couldn't find a text channel matching `{raw}`")

        await upsert(self.bot, ctx.guild.id, alert_channel_id=target.id)
        return await ctx.success(f"Honeypot alerts will post in {target.mention}")

    @honeypot.command(
        name="punishment",
        aliases=["action", "punish"],
        description="set the punishment(s). choose one or more of: kick, ban, hardban, softban, timeout, jail",
        example=",honeypot punishment softban",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_punishment(self, ctx, *, actions: str | None = None):
        """Set the punishment(s). Choose one or more of: kick, ban, softban, timeout."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id) or {}
        if not actions or not str(actions).strip():
            current = _normalize_punishments(row.get("punishments"))
            return await ctx.send(
                embed=panel_embed(
                    color=None,
                    title="Honeypot Punishment",
                    lines=[
                        f"**Current**: {_punishment_phrase(current)}",
                        "> -# Options: `kick`, `ban`, `hardban`, `softban`, `timeout`, `jail`",
                        f"> -# Example: `{ctx.invoke_prefix}honeypot punishment ban timeout`",
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

        invalid = [t for t in tokens if t not in _VALID_PUNISHMENTS and t not in {"hard"}]
        if invalid:
            return await ctx.warn(
                f"Invalid punishment(s): {', '.join(f'`{t}`' for t in invalid)} - "
                f"use `kick`, `ban`, `hardban`, `softban`, `timeout`, or `jail`"
            )

        punishments = _normalize_punishments(tokens)
        if "hardban" in punishments:
            
            try:
                an_row = await self.db.fetchrow(
                    "SELECT admins, ban, kick, channel, role, webhook, emoji, vanity, botadd FROM antinuke WHERE guild_id = $1",
                    ctx.guild.id,
                )
            except Exception:
                an_row = None
            enabled = False
            if an_row:
                import json
                for key in ("ban", "kick", "channel", "role", "webhook", "emoji", "vanity", "botadd"):
                    val = an_row[key] if not hasattr(an_row, "get") else an_row.get(key)
                    if isinstance(val, str):
                        try:
                            val = json.loads(val)
                        except Exception:
                            val = {}
                    if isinstance(val, dict) and val.get("status"):
                        enabled = True
                        break
            if not enabled:
                return await ctx.warn(
                    "antinuke isn't enabled in this guild\n"
                    "> -# **enable it using** `antinuke setup`"
                )
            is_admin = ctx.author.id == ctx.guild.owner_id
            if not is_admin and an_row is not None:
                admins = an_row["admins"] if not hasattr(an_row, "get") else an_row.get("admins")
                admins = list(admins or [])
                is_admin = ctx.author.id in admins
            if not is_admin:
                return await ctx.warn(
                    "You are missing permissions to set it to this punishment\n"
                    "> -# **Permission Needed: Antinuke Admin**"
                )
        updated = await upsert(self.bot, ctx.guild.id, punishments=punishments)

        
        if updated.get("enabled"):
            await self._refresh_trap_message(ctx.guild, updated)

        return await ctx.success(
            f"Honeypot punishment set to {_punishment_phrase(punishments)}"
        )

    @honeypot.command(
        name="settings",
        aliases=["setting", "view", "show"],
        description="view the current honeypot configuration",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_settings(self, ctx):
        """View the current honeypot configuration."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id)
        if not row:
            return await ctx.warn(
                f"Honeypot is not configured - use `{ctx.invoke_prefix}honeypot setup`"
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
        description="set a custom embed/container script for the honeypot trap message",
        example=",honeypot embed {container}$v{description: Do not post here}",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_embed(self, ctx, *, script: str | None = None):
        """Customize the trap message with an embed or container script."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        row = await fetch(self.bot, ctx.guild.id) or {}
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
                            f"> -# Use `{ctx.invoke_prefix}honeypot embed <script>` to customize",
                            f"> -# Use `{ctx.invoke_prefix}honeypot embed clear` to reset",
                            f"> -# Variables: `{ctx.invoke_prefix}variables honeypot`",
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
                        f"> -# Use `{ctx.invoke_prefix}honeypot embed clear` to reset",
                        f"> -# Variables: `{ctx.invoke_prefix}variables honeypot`",
                    ],
                    timestamp=False,
                )
            )

        if raw.lower() in {"clear", "none", "off", "reset", "default", "remove"}:
            updated = await upsert(self.bot, ctx.guild.id, embed_script=None)
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

        updated = await upsert(self.bot, ctx.guild.id, embed_script=raw)
        if updated.get("enabled"):
            await self._refresh_trap_message(ctx.guild, updated)
        return await ctx.success(
            f"Honeypot trap embed updated - see `{ctx.invoke_prefix}variables honeypot` for vars"
        )
