"""Ping members in selected channels when they join."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord import Embed, TextChannel, Message
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.tools.moderation_args import is_duration_token, parse_duration_seconds

from .events import (
    DEFAULT_DELETE_AFTER,
    DEFAULT_DELETE_ENABLED,
    PingOnJoinEvents,
)

if TYPE_CHECKING:
    from core.vain import Vain


def _parse_delete_seconds(token: str) -> int | None:
    raw = (token or "").strip().lower()
    if not raw:
        return None
    if raw.isdigit():
        return max(1, min(int(raw), 600))
    if is_duration_token(raw):
        sec = parse_duration_seconds(raw)
        if sec is None:
            return None
        return max(1, min(int(sec), 600))
    return None


class PingOnJoinCommands(PingOnJoinEvents, Package):
    """Ping new members in one or more channels."""

    @group(
        name="pingonjoin",
        aliases=["poj", "joinping"],
        invoke_without_command=True,
        description="ping members in a channel when they join",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin(self, ctx) -> Message:
        return await ctx.send_help(ctx.command)

    @pingonjoin.command(
        name="add",
        aliases=["set", "create"],
        example=",pingonjoin add #welcome",
        description="add a channel that will ping new members (defaults to current channel)",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_add(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self._ensure_table()
        ids = await self._get_channels(ctx.guild.id)
        if channel.id in ids:
            return await ctx.warn(f"{channel.mention} is already a ping-on-join channel")
        ids.append(channel.id)
        await self._set_channels(ctx.guild.id, ids)
        return await ctx.success(f"New members will be **pinged** in {channel.mention}")

    @pingonjoin.command(
        name="remove",
        aliases=["del", "rm"],
        example=",pingonjoin remove #welcome",
        description="remove a ping on join channel (defaults to current channel)",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_remove(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self._ensure_table()
        ids = await self._get_channels(ctx.guild.id)
        if channel.id not in ids:
            return await ctx.warn(f"{channel.mention} is not a ping-on-join channel")
        ids = [i for i in ids if i != channel.id]
        await self._set_channels(ctx.guild.id, ids)
        return await ctx.success(f"Removed ping on join from {channel.mention}")

    @pingonjoin.command(
        name="list",
        aliases=["show", "view"],
        description="list ping on join channels and settings",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_list(self, ctx) -> Message:
        await self._ensure_table()
        row = await self._get_pingonjoin_row(ctx.guild.id)
        ids = [int(i) for i in (row.get("channel_ids") or [])]
        if not ids:
            return await ctx.search("no ping on join channels set")
        lines = []
        for cid in ids:
            ch = ctx.guild.get_channel(cid)
            if ch:
                lines.append(f"{ch.mention} (`{cid}`)")
            else:
                lines.append(f"`{cid}` *(missing)*")
        delete_on = bool(row.get("delete_enabled", DEFAULT_DELETE_ENABLED))
        delete_after = int(row.get("delete_after") or DEFAULT_DELETE_AFTER)
        script = row.get("message")
        footer = (
            f"delete: **{'on' if delete_on else 'off'}** · delay **{delete_after}s**"
            + (f" · custom script set" if script else " · default mention")
        )
        emb = Embed(
            title="Ping on Join",
            description="\n".join(lines) + f"\n\n> -# {footer}",
            color=self.color,
        )
        return await ctx.reply(embed=emb)

    @pingonjoin.command(
        name="clear",
        aliases=["reset"],
        description="Clear all ping on join channels. This **can't be undone**.",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_clear(self, ctx) -> Message:
        await self._ensure_table()
        ids = await self._get_channels(ctx.guild.id)
        if not ids:
            return await ctx.warn("No ping on join channels are configured")

        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** ping on join channels? This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Ping on join clear **cancelled**")

        await self._set_channels(ctx.guild.id, [])
        return await ctx.success(
            "Cleared all **ping on join** channels. This action can't be undone."
        )

    @pingonjoin.group(
        name="message",
        aliases=["script", "msg", "template"],
        invoke_without_command=True,
        usage="[script]",
        example=",pingonjoin message welcome {user.mention}!",
        description="set the custom ping on join message script",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_message(self, ctx, *, script: str = None) -> Message:
        """Set a custom message/script for all ping on join channels.

        Uses the same embed script syntax as welcome/tag.
        Leave empty to view the current script. Use `remove` to clear.
        """
        await self._ensure_table()
        if not script or not str(script).strip():
            row = await self._get_pingonjoin_row(ctx.guild.id)
            current = row.get("message")
            if current:
                return await ctx.send(f"```\n{str(current)[:1900]}\n```")
            return await ctx.success(
                "Using the **default** ping (just a mention). "
                f"Set one with {ctx.cmd('pingonjoin message <script>')}"
            )
        if script.strip().lower() in {"clear", "reset", "default", "none", "remove"}:
            await self._set_message(ctx.guild.id, None)
            return await ctx.success("Ping-on-join message **reset** to default mention")
        await self._set_message(ctx.guild.id, script.strip())
        return await ctx.success("Updated **ping on join** message script")

    @pingonjoin_message.command(
        name="remove",
        aliases=["delete", "del", "rm", "clear", "reset"],
        description="reset the ping on join message to the default mention",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_message_remove(self, ctx) -> Message:
        await self._ensure_table()
        row = await self._get_pingonjoin_row(ctx.guild.id)
        if not row.get("message"):
            return await ctx.warn("No custom ping on join message has been set")
        await self._set_message(ctx.guild.id, None)
        return await ctx.success("Ping-on-join message **reset** to default mention")

    @pingonjoin.group(
        name="delete",
        aliases=["deletedelay", "autodelete"],
        invoke_without_command=True,
        usage="[on or off or interval]",
        example=",pingonjoin delete 10s",
        description="auto-delete ping on join messages after a delay",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_delete(self, ctx, *, option: str = None) -> Message:
        """Control auto-delete for ping on join messages.

        Examples:
        - {ctx.cmd('poj delete')} - show current settings
        - {ctx.cmd('poj delete on')} / `enable` - turn auto-delete on
        - {ctx.cmd('poj delete off')} / `disable` - turn auto-delete off
        - {ctx.cmd('poj delete 10s')} / `30` - set delay (default **10s**)
        """
        await self._ensure_table()
        if not option or not str(option).strip():
            row = await self._get_pingonjoin_row(ctx.guild.id)
            on = bool(row.get("delete_enabled", DEFAULT_DELETE_ENABLED))
            after = int(row.get("delete_after") or DEFAULT_DELETE_AFTER)
            return await ctx.success(
                f"Auto-delete is **{'on' if on else 'off'}** · delay **{after}s**"
            )

        raw = option.strip().lower()

        
        if raw in {"on", "enable", "enabled", "true", "yes", "1"}:
            await self._set_delete(ctx.guild.id, enabled=True)
            row = await self._get_pingonjoin_row(ctx.guild.id)
            after = int(row.get("delete_after") or DEFAULT_DELETE_AFTER)
            return await ctx.success(
                f"Auto-delete **enabled** · pings delete after **{after}s**"
            )

        
        if raw in {"off", "disable", "disabled", "false", "no", "0"}:
            await self._set_delete(ctx.guild.id, enabled=False)
            return await ctx.success("Auto-delete **disabled** · pings will stay")

        
        seconds = _parse_delete_seconds(raw)
        if seconds is not None:
            await self._set_delete(ctx.guild.id, enabled=True, after=seconds)
            return await ctx.success(
                f"Auto-delete **enabled** · delay set to **{seconds}s**"
            )

        return await ctx.warn(
            "Use `on`, `off`, or a duration like `10s` / `30` "
            "(aliases: `enable`, `disable`)"
        )

    @pingonjoin_delete.command(
        name="enable",
        aliases=["on"],
        description="enable auto-delete for ping on join messages",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_delete_enable(self, ctx) -> Message:
        await self._ensure_table()
        await self._set_delete(ctx.guild.id, enabled=True)
        row = await self._get_pingonjoin_row(ctx.guild.id)
        after = int(row.get("delete_after") or DEFAULT_DELETE_AFTER)
        return await ctx.success(
            f"Auto-delete **enabled** · pings delete after **{after}s**"
        )

    @pingonjoin_delete.command(
        name="disable",
        aliases=["off"],
        description="disable auto-delete for ping on join messages",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin_delete_disable(self, ctx) -> Message:
        await self._ensure_table()
        await self._set_delete(ctx.guild.id, enabled=False)
        return await ctx.success("Auto-delete **disabled** · pings will stay")


PingOnJoin = PingOnJoinCommands

__all__ = ["PingOnJoinCommands", "PingOnJoin"]
