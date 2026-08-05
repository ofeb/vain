from __future__ import annotations

import contextlib
from asyncio import Lock
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import Embed, TextChannel
from discord.ext import tasks
from discord.ext.commands import CommandError, TextChannelConverter, group

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.tools.moderation_args import (
    format_duration_token,
    is_duration_token,
    parse_duration_seconds,
)
from humanize import naturaldelta

_DEFAULT_MESSAGE_LIMIT = 5
_DEFAULT_INTERVAL_SECONDS = 300


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StickymessageCommands(Package):
    """Sticky messages that re-post after N messages or after an idle interval."""

    def __init__(self, bot):
        super().__init__(bot)
        self.sticky_locks: dict[int, Lock] = defaultdict(Lock)
        self.pinned_ids: dict[int, int] = {}
        self._msg_counts: dict[int, int] = defaultdict(int)
        self._last_activity: dict[int, datetime] = {}

    async def cog_load(self) -> None:
        await self._ensure_schema()
        if not self._sticky_interval_loop.is_running():
            self._sticky_interval_loop.start()

    async def _ensure_schema(self) -> None:
        statements = [
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS message_limit INT NOT NULL DEFAULT 5",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS interval_seconds INT NOT NULL DEFAULT 300",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS message_count INT NOT NULL DEFAULT 0",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS last_sent TIMESTAMP",
        ]
        for sql in statements:
            try:
                await self.db.execute(sql)
            except Exception:
                pass

    async def cog_unload(self) -> None:
        if self._sticky_interval_loop.is_running():
            self._sticky_interval_loop.cancel()

    async def _get_row(self, guild_id: int, channel_id: int) -> dict | None:
        row = await self.db.fetchrow(
            """SELECT guild_id, channel_id, code, last_message,
                      COALESCE(message_limit, $3) AS message_limit,
                      COALESCE(interval_seconds, $4) AS interval_seconds,
                      COALESCE(message_count, 0) AS message_count,
                      last_sent
               FROM sticky_message
               WHERE guild_id = $1 AND channel_id = $2""",
            guild_id, channel_id, _DEFAULT_MESSAGE_LIMIT, _DEFAULT_INTERVAL_SECONDS,
        )
        return dict(row) if row else None

    async def _repost(self, channel: TextChannel, code: str, *, user=None):
        async with self.sticky_locks[channel.id]:
            row = await self._get_row(channel.guild.id, channel.id)
            prev_id = self.pinned_ids.get(channel.id)
            if prev_id is None and row:
                prev_id = row.get("last_message")
            if prev_id:
                with contextlib.suppress(discord.NotFound, discord.HTTPException, discord.Forbidden):
                    await self.bot.http.delete_message(channel.id, prev_id)
            try:
                new_msg = await self.bot.send_embed(channel, code, user=user or channel.guild.me)
            except Exception:
                try:
                    new_msg = await channel.send(content=(code or "")[:2000])
                except (discord.Forbidden, discord.HTTPException):
                    return None
            if new_msg is None:
                return None
            now = _now_naive()
            await self.db.execute(
                """UPDATE sticky_message SET last_message = $1, message_count = 0, last_sent = $2
                   WHERE guild_id = $3 AND channel_id = $4""",
                new_msg.id, now, channel.guild.id, channel.id,
            )
            self.pinned_ids[channel.id] = new_msg.id
            self._msg_counts[channel.id] = 0
            return new_msg

    async def _resolve_add(self, ctx, raw: str):
        tokens = raw.split() if raw else []
        channel: TextChannel = ctx.channel
        message_limit = _DEFAULT_MESSAGE_LIMIT
        interval_seconds = _DEFAULT_INTERVAL_SECONDS
        i = 0
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                i = 1
            except Exception:
                pass
        body = tokens[i:]
        if body and is_duration_token(body[-1]):
            secs = parse_duration_seconds(body[-1])
            if secs is not None and secs >= 30:
                interval_seconds = secs
                body = body[:-1]
        if body and body[-1].isdigit():
            limit = int(body[-1])
            if 1 <= limit <= 100:
                message_limit = limit
                body = body[:-1]
            elif int(body[-1]) > 100:
                raise CommandError("message limit must be between **1** and **100**")
        script = " ".join(body).strip()
        if not script:
            raise CommandError(
                f"Provide a sticky script/message\nExample: `{ctx.clean_prefix}stickymessage add #general hello 5 5m`"
            )
        if not isinstance(channel, TextChannel):
            raise CommandError("You can only set sticky messages in text channels")
        if interval_seconds < 30:
            raise CommandError("Interval must be at least **30 seconds**")
        return channel, script, message_limit, interval_seconds

    @group(name="stickymessage", aliases=["sticky", "stickymsg"], description="Set up sticky messages that re-post every N messages or after an idle interval", invoke_without_command=True, example=",stickymessage add #general Stay on topic! 5 5m")
    @has_permissions(manage_guild=True)
    async def stickymessage(self, ctx):
        return await ctx.send_help(ctx.command)

    @stickymessage.command(name="add", aliases=["set", "create"], description="Add a sticky message to a channel", example=",stickymessage add #general Stay on topic! 5 5m", usage="[channel] <script> [message_limit] [interval]")
    @has_permissions(manage_guild=True)
    async def stickymessage_add(self, ctx, *, args: str = ""):
        channel, script, message_limit, interval_seconds = await self._resolve_add(ctx, args)
        await self.db.execute(
            """INSERT INTO sticky_message (guild_id, channel_id, code, message_limit, interval_seconds, message_count, last_sent)
               VALUES ($1, $2, $3, $4, $5, 0, $6)
               ON CONFLICT (guild_id, channel_id) DO UPDATE SET code = excluded.code, message_limit = excluded.message_limit,
                   interval_seconds = excluded.interval_seconds, message_count = 0, last_sent = excluded.last_sent""",
            ctx.guild.id, channel.id, script, message_limit, interval_seconds, _now_naive(),
        )
        self._msg_counts[channel.id] = 0
        new_msg = await self._repost(channel, script, user=ctx.author)
        extra = f"\n-# initial sticky posted · {new_msg.jump_url}" if new_msg else ""
        return await ctx.success(
            f"Sticky set in {channel.mention}\n• every **{message_limit}** message(s)\n• or after **{naturaldelta(interval_seconds)}** if the limit isn't met{extra}"
        )

    @stickymessage.command(name="edit", aliases=["update"], description="Edit a sticky's script, message limit, and/or interval", example=",stickymessage edit #general New text 10 10m", usage="[channel] <script> [message_limit] [interval]")
    @has_permissions(manage_guild=True)
    async def stickymessage_edit(self, ctx, *, args: str = ""):
        channel, script, message_limit, interval_seconds = await self._resolve_add(ctx, args)
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(f"No sticky in {channel.mention} — use `{ctx.clean_prefix}stickymessage add` first")
        await self.db.execute(
            """UPDATE sticky_message SET code = $1, message_limit = $2, interval_seconds = $3, message_count = 0, last_sent = $4
               WHERE guild_id = $5 AND channel_id = $6""",
            script, message_limit, interval_seconds, _now_naive(), ctx.guild.id, channel.id,
        )
        self._msg_counts[channel.id] = 0
        await self._repost(channel, script, user=ctx.author)
        return await ctx.success(f"Updated sticky in {channel.mention}\n• every **{message_limit}** message(s)\n• or after **{naturaldelta(interval_seconds)}**")

    @stickymessage.command(name="interval", aliases=["changeinterval", "ci"], description="Change the auto-send interval for a sticky", example=",stickymessage interval #general 10m", usage="[channel] <interval>")
    @has_permissions(manage_guild=True)
    async def stickymessage_interval(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel
        interval_token = None
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                rest = tokens[1:]
            except Exception:
                rest = tokens
            if rest:
                interval_token = rest[0]
        if not interval_token or not is_duration_token(interval_token):
            raise CommandError(f"Provide an interval (e.g. `30s`, `5m`, `1h`, `1d`)\nExample: `{ctx.clean_prefix}stickymessage interval #general 10m`")
        seconds = parse_duration_seconds(interval_token)
        if seconds is None or seconds < 30:
            raise CommandError("Interval must be at least **30 seconds**")
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(f"No sticky in {channel.mention}")
        await self.db.execute("UPDATE sticky_message SET interval_seconds = $1 WHERE guild_id = $2 AND channel_id = $3", seconds, ctx.guild.id, channel.id)
        return await ctx.success(f"Sticky interval for {channel.mention} set to **{naturaldelta(seconds)}** (`{format_duration_token(seconds)}`)")

    @stickymessage.command(name="messagelimit", aliases=["changemessagelimit", "cml", "limit"], description="Change how many messages trigger a sticky re-post", example=",stickymessage messagelimit #general 10", usage="[channel] <limit>")
    @has_permissions(manage_guild=True)
    async def stickymessage_messagelimit(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel
        limit_token = None
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                rest = tokens[1:]
            except Exception:
                rest = tokens
            if rest:
                limit_token = rest[0]
        if not limit_token or not limit_token.isdigit():
            raise CommandError(f"Provide a message limit between **1** and **100**\nExample: `{ctx.clean_prefix}stickymessage messagelimit #general 10`")
        limit = int(limit_token)
        if not 1 <= limit <= 100:
            raise CommandError("Message limit must be between **1** and **100**")
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(f"No sticky in {channel.mention}")
        await self.db.execute("UPDATE sticky_message SET message_limit = $1, message_count = 0 WHERE guild_id = $2 AND channel_id = $3", limit, ctx.guild.id, channel.id)
        self._msg_counts[channel.id] = 0
        return await ctx.success(f"Sticky message limit for {channel.mention} set to **{limit}**")

    @stickymessage.command(name="view", aliases=["preview", "show"], description="View the sticky message for a channel", example=",stickymessage view #general", usage="[channel]")
    @has_permissions(manage_guild=True)
    async def stickymessage_view(self, ctx, channel: Optional[TextChannel] = None):
        channel = channel or ctx.channel
        row = await self._get_row(ctx.guild.id, channel.id)
        if not row:
            raise CommandError(f"No sticky message in {channel.mention}")
        await ctx.normal(f"**Sticky in {channel.mention}**\n• every **{row['message_limit']}** message(s)\n• or after **{naturaldelta(row['interval_seconds'])}**\n• current count: **{self._msg_counts.get(channel.id, row.get('message_count') or 0)}**")
        return await self.bot.send_embed(ctx.channel, row["code"], user=ctx.author)

    @stickymessage.command(name="list", aliases=["ls"], description="View all sticky messages in this server", example=",stickymessage list")
    @has_permissions(manage_guild=True)
    async def stickymessage_list(self, ctx):
        entries = await self.db.fetch(
            """SELECT channel_id, code, COALESCE(message_limit, $2) AS message_limit, COALESCE(interval_seconds, $3) AS interval_seconds
               FROM sticky_message WHERE guild_id = $1""",
            ctx.guild.id, _DEFAULT_MESSAGE_LIMIT, _DEFAULT_INTERVAL_SECONDS,
        )
        if not entries:
            raise CommandError("No sticky messages exist")
        lines = []
        for i, e in enumerate(entries, start=1):
            ch = ctx.guild.get_channel(e["channel_id"])
            label = ch.mention if ch else f"`{e['channel_id']}`"
            lines.append(f"`{i}` {label} — every **{e['message_limit']}** msgs / **{naturaldelta(e['interval_seconds'])}**")
        return await ctx.paginate(Embed(title="Sticky Messages", color=self.bot.color).set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url), lines)

    @stickymessage.command(name="remove", aliases=["delete", "del", "rm"], description="Remove a sticky message from a channel", example=",stickymessage remove #general", usage="[channel]")
    @has_permissions(manage_guild=True)
    async def stickymessage_remove(self, ctx, channel: Optional[TextChannel] = None):
        channel = channel or ctx.channel
        row = await self._get_row(ctx.guild.id, channel.id)
        if not row:
            raise CommandError(f"No sticky in {channel.mention}")
        prev_id = self.pinned_ids.pop(channel.id, None) or row.get("last_message")
        if prev_id:
            with contextlib.suppress(discord.NotFound, discord.HTTPException, discord.Forbidden):
                await self.bot.http.delete_message(channel.id, prev_id)
        await self.db.execute("DELETE FROM sticky_message WHERE guild_id = $1 AND channel_id = $2", ctx.guild.id, channel.id)
        self._msg_counts.pop(channel.id, None)
        self._last_activity.pop(channel.id, None)
        return await ctx.success(f"Sticky removed from {channel.mention}")

    @stickymessage.group(
        name="change",
        aliases=["cfg", "config"],
        description="Change sticky settings (interval, message limit, script)",
        invoke_without_command=True,
        example=",stickymessage change interval 10m",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_change(self, ctx):
        return await ctx.send_help(ctx.command)

    @stickymessage_change.command(
        name="interval",
        aliases=["changeinterval", "ci"],
        description="Change sticky auto-send interval",
        example=",stickymessage change interval #general 10m",
        usage="[channel] <interval>",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_change_interval(self, ctx, *, args: str = ""):
        return await self.stickymessage_interval(ctx, args=args)

    @stickymessage_change.command(
        name="messagelimit",
        aliases=["limit", "cml", "changemessagelimit"],
        description="Change sticky message limit",
        example=",stickymessage change messagelimit #general 10",
        usage="[channel] <limit>",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_change_messagelimit(self, ctx, *, args: str = ""):
        return await self.stickymessage_messagelimit(ctx, args=args)

    @stickymessage_change.command(
        name="script",
        aliases=["message", "embed", "code"],
        description="Change only the sticky script for a channel",
        example=",stickymessage change script #general Stay on topic!",
        usage="[channel] <script>",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_change_script(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
        i = 0
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                i = 1
            except Exception:
                pass
        script = " ".join(tokens[i:]).strip()
        if not script:
            raise CommandError("Provide a sticky script/message")
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(f"No sticky in {channel.mention}")
        await self.db.execute(
            "UPDATE sticky_message SET code = $1 WHERE guild_id = $2 AND channel_id = $3",
            script,
            ctx.guild.id,
            channel.id,
        )
        await self._repost(channel, script, user=ctx.author)
        return await ctx.success(f"Updated sticky script in {channel.mention}")

    async def on_valid_message(self, ctx) -> None:
        if not getattr(ctx, "guild", None) or not getattr(ctx, "channel", None):
            return
        if getattr(ctx.author, "bot", False):
            return
        channel = ctx.channel
        if not isinstance(channel, TextChannel):
            return
        row = await self._get_row(ctx.guild.id, channel.id)
        if not row:
            return
        last_id = self.pinned_ids.get(channel.id) or row.get("last_message")
        if getattr(ctx.message, "id", None) and last_id and ctx.message.id == last_id:
            return
        self._msg_counts[channel.id] = self._msg_counts.get(channel.id, 0) + 1
        self._last_activity[channel.id] = _now_naive()
        count = self._msg_counts[channel.id]
        limit = int(row["message_limit"] or _DEFAULT_MESSAGE_LIMIT)
        await self.db.execute("UPDATE sticky_message SET message_count = $1 WHERE guild_id = $2 AND channel_id = $3", count, ctx.guild.id, channel.id)
        if count >= limit:
            await self._repost(channel, row["code"], user=ctx.author)

    @tasks.loop(seconds=30.0)
    async def _sticky_interval_loop(self) -> None:
        """Re-post sticky when there was activity but the message limit wasn't hit.

        Example: limit=5, interval=5m. User sends 1–4 messages then goes quiet —
        after 5 minutes from last sticky (or last activity window), re-post.
        Completely idle channels (0 messages since last sticky) are skipped.
        """
        if getattr(self.db, "pool", None) is None:
            return
        try:
            rows = await self.db.fetch(
                """SELECT guild_id, channel_id, code,
                          COALESCE(interval_seconds, $1) AS interval_seconds,
                          COALESCE(message_count, 0) AS message_count,
                          last_sent
                   FROM sticky_message""",
                _DEFAULT_INTERVAL_SECONDS,
            )
        except Exception:
            return
        now = _now_naive()
        for row in rows:
            try:
                interval = int(row["interval_seconds"] or _DEFAULT_INTERVAL_SECONDS)
                if interval < 30:
                    continue
                channel_id = int(row["channel_id"])
                
                count = self._msg_counts.get(
                    channel_id, int(row.get("message_count") or 0)
                )
                
                if count <= 0 and channel_id not in self._last_activity:
                    continue
                last_sent = row["last_sent"]
                if last_sent is not None and getattr(last_sent, "tzinfo", None) is not None:
                    last_sent = last_sent.replace(tzinfo=None)
                
                anchor = last_sent or self._last_activity.get(channel_id)
                if anchor is not None and (now - anchor).total_seconds() < interval:
                    continue
                guild = self.bot.get_guild(row["guild_id"])
                if guild is None:
                    continue
                channel = guild.get_channel(channel_id)
                if channel is None or not isinstance(channel, TextChannel):
                    continue
                await self._repost(channel, row["code"])
            except Exception:
                continue

    @_sticky_interval_loop.before_loop
    async def _before_sticky_interval_loop(self) -> None:
        await self.bot.wait_until_ready()
