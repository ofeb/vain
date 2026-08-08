from __future__ import annotations

import asyncio
import contextlib
from asyncio import Lock, Queue
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


_DEFAULT_MESSAGE_LIMIT = 1
_DEFAULT_INTERVAL_SECONDS = 300  
_INTERVAL_DISABLED = 0

_REPOST_MIN_GAP_SECONDS = 1.35


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_trigger(message_limit: int, interval_seconds: int) -> str:
    if int(message_limit) <= 1:
        return "after **every** message (rate-limited queue)"
    parts = [f"every **{message_limit}** message(s)"]
    if int(interval_seconds or 0) >= 30:
        parts.append(f"or after **{naturaldelta(interval_seconds)}** idle")
    return " · ".join(parts)


class StickymessageCommands(Package):
    """Sticky messages that re-post after N messages and/or after an idle interval."""

    def __init__(self, bot):
        super().__init__(bot)
        self.sticky_locks: dict[int, Lock] = defaultdict(Lock)
        self.pinned_ids: dict[int, int] = {}
        self._msg_counts: dict[int, int] = defaultdict(int)
        self._last_activity: dict[int, datetime] = {}
        
        self._pending_repost: set[int] = set()
        self._queue: Queue[tuple[int, int, str, object | None]] = Queue()
        self._worker_task: asyncio.Task | None = None
        self._last_repost_at: dict[int, float] = {}

    async def cog_load(self) -> None:
        await self._ensure_schema()
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._sticky_queue_worker())
        if not self._sticky_interval_loop.is_running():
            self._sticky_interval_loop.start()

    async def _ensure_schema(self) -> None:
        if getattr(self, "_sticky_schema_ready", False):
            return
        statements = [
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS message_limit INT NOT NULL DEFAULT 1",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS interval_seconds INT NOT NULL DEFAULT 0",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS message_count INT NOT NULL DEFAULT 0",
            "ALTER TABLE sticky_message ADD COLUMN IF NOT EXISTS last_sent TIMESTAMP",
        ]
        for sql in statements:
            with contextlib.suppress(Exception):
                await self.db.execute(sql)
        self._sticky_schema_ready = True

    async def cog_unload(self) -> None:
        if self._sticky_interval_loop.is_running():
            self._sticky_interval_loop.cancel()
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        self._worker_task = None

    async def _get_row(self, guild_id: int, channel_id: int) -> dict | None:
        row = await self.db.fetchrow(
            """SELECT guild_id, channel_id, code, last_message,
                      COALESCE(message_limit, $3) AS message_limit,
                      COALESCE(interval_seconds, $4) AS interval_seconds,
                      COALESCE(message_count, 0) AS message_count,
                      last_sent
               FROM sticky_message
               WHERE guild_id = $1 AND channel_id = $2""",
            guild_id,
            channel_id,
            _DEFAULT_MESSAGE_LIMIT,
            _INTERVAL_DISABLED,
        )
        return dict(row) if row else None

    async def _repost(self, channel: TextChannel, code: str, *, user=None):
        async with self.sticky_locks[channel.id]:
            
            loop = asyncio.get_running_loop()
            now_m = loop.time()
            last = self._last_repost_at.get(channel.id, 0.0)
            wait = _REPOST_MIN_GAP_SECONDS - (now_m - last)
            if wait > 0:
                await asyncio.sleep(wait)

            row = await self._get_row(channel.guild.id, channel.id)
            prev_id = self.pinned_ids.get(channel.id)
            if prev_id is None and row:
                prev_id = row.get("last_message")
            if prev_id:
                with contextlib.suppress(
                    discord.NotFound, discord.HTTPException, discord.Forbidden
                ):
                    await self.bot.http.delete_message(channel.id, prev_id)
            try:
                new_msg = await self.bot.send_embed(
                    channel, code, user=user or channel.guild.me
                )
            except Exception:
                try:
                    new_msg = await channel.send(content=(code or "")[:2000])
                except (discord.Forbidden, discord.HTTPException) as exc:
                    
                    if isinstance(exc, discord.HTTPException) and exc.status == 429:
                        retry = float(getattr(exc, "retry_after", 2.0) or 2.0)
                        await asyncio.sleep(min(max(retry, 1.0), 15.0))
                    return None
            if new_msg is None:
                return None
            now = _now_naive()
            await self.db.execute(
                """UPDATE sticky_message
                   SET last_message = $1, message_count = 0, last_sent = $2
                   WHERE guild_id = $3 AND channel_id = $4""",
                new_msg.id,
                now,
                channel.guild.id,
                channel.id,
            )
            self.pinned_ids[channel.id] = new_msg.id
            self._msg_counts[channel.id] = 0
            self._last_repost_at[channel.id] = asyncio.get_running_loop().time()
            return new_msg

    def _ensure_runtime(self) -> None:
        """Server mixin may not call this class's __init__/cog_load — start lazily."""
        if not hasattr(self, "_pending_repost") or self._pending_repost is None:
            self._pending_repost = set()
        if not hasattr(self, "_last_repost_at") or self._last_repost_at is None:
            self._last_repost_at = {}
        if not hasattr(self, "_queue") or self._queue is None:
            self._queue = Queue()
        if not hasattr(self, "sticky_locks") or self.sticky_locks is None:
            self.sticky_locks = defaultdict(Lock)
        if not hasattr(self, "pinned_ids") or self.pinned_ids is None:
            self.pinned_ids = {}
        if not hasattr(self, "_msg_counts") or self._msg_counts is None:
            self._msg_counts = defaultdict(int)
        if not hasattr(self, "_last_activity") or self._last_activity is None:
            self._last_activity = {}
        
        if not getattr(self, "_sticky_schema_ready", False):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ensure_schema())
            except Exception:
                pass
        task = getattr(self, "_worker_task", None)
        if task is None or getattr(task, "done", lambda: True)():
            try:
                self._worker_task = asyncio.create_task(self._sticky_queue_worker())
            except Exception:
                self._worker_task = None
        loop = getattr(self, "_sticky_interval_loop", None)
        if loop is not None and not loop.is_running():
            with contextlib.suppress(Exception):
                loop.start()

    def _enqueue_repost(
        self,
        guild_id: int,
        channel_id: int,
        code: str,
        user=None,
    ) -> None:
        """Coalesce: at most one pending job per channel."""
        self._ensure_runtime()
        if channel_id in self._pending_repost:
            return
        self._pending_repost.add(channel_id)
        self._queue.put_nowait((guild_id, channel_id, code, user))

    async def _sticky_queue_worker(self) -> None:
        """Drain sticky reposts slowly so chat bursts don't flood the API."""
        while True:
            guild_id, channel_id, code, user = await self._queue.get()
            try:
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    continue
                channel = guild.get_channel(channel_id)
                if channel is None or not isinstance(channel, TextChannel):
                    continue
                
                row = await self._get_row(guild_id, channel_id)
                if not row:
                    continue
                await self._repost(channel, row.get("code") or code, user=user)
            except asyncio.CancelledError:
                raise
            except Exception:
                
                await asyncio.sleep(0.5)
            finally:
                self._pending_repost.discard(channel_id)
                self._queue.task_done()
                
                await asyncio.sleep(0.35)

    async def _resolve_add(self, ctx, raw: str):
        tokens = raw.split() if raw else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
        
        message_limit = _DEFAULT_MESSAGE_LIMIT
        interval_seconds = _INTERVAL_DISABLED
        saw_limit = False
        saw_interval = False
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
                saw_interval = True
                body = body[:-1]
        
        if body and body[-1].isdigit():
            limit = int(body[-1])
            if 1 <= limit <= 100:
                message_limit = limit
                saw_limit = True
                body = body[:-1]
            elif int(body[-1]) > 100:
                raise CommandError("message limit must be between **1** and **100**")
        script = " ".join(body).strip()
        if not script:
            raise CommandError(
                "Provide a sticky script/message\n"
                f"Example: `{ctx.clean_prefix}stickymessage add #general stay on topic`\n"
                f"With options: `{ctx.clean_prefix}stickymessage add #general hello 5 5m`"
            )
        if not isinstance(channel, TextChannel):
            raise CommandError("You can only set sticky messages in text channels")

        
        
        
        
        
        
        if message_limit <= 1:
            interval_seconds = _INTERVAL_DISABLED
        else:
            if not saw_interval:
                interval_seconds = _DEFAULT_INTERVAL_SECONDS
        
        if saw_interval and not saw_limit:
            
            
            message_limit = 5
            if interval_seconds < 30:
                interval_seconds = _DEFAULT_INTERVAL_SECONDS

        if interval_seconds not in (0, _INTERVAL_DISABLED) and interval_seconds < 30:
            raise CommandError("Interval must be at least **30 seconds** (or omit for none)")
        return channel, script, message_limit, interval_seconds

    @group(
        name="stickymessage",
        aliases=["sticky", "stickymsg"],
        description="Sticky messages that re-post every N messages or after an idle interval",
        invoke_without_command=True,
        example=",stickymessage add #general stay on topic",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage(self, ctx):
        return await ctx.send_help(ctx.command)

    @stickymessage.command(
        name="add",
        aliases=["set", "create"],
        description="Add a sticky message (default: after every message, rate-limited)",
        example=",stickymessage add #general stay on topic",
        usage="[channel] <script> [message_limit] [interval]",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_add(self, ctx, *, args: str = ""):
        channel, script, message_limit, interval_seconds = await self._resolve_add(
            ctx, args
        )
        await self.db.execute(
            """INSERT INTO sticky_message
                   (guild_id, channel_id, code, message_limit, interval_seconds, message_count, last_sent)
               VALUES ($1, $2, $3, $4, $5, 0, $6)
               ON CONFLICT (guild_id, channel_id) DO UPDATE SET
                   code = excluded.code,
                   message_limit = excluded.message_limit,
                   interval_seconds = excluded.interval_seconds,
                   message_count = 0,
                   last_sent = excluded.last_sent""",
            ctx.guild.id,
            channel.id,
            script,
            message_limit,
            interval_seconds,
            _now_naive(),
        )
        self._msg_counts[channel.id] = 0
        new_msg = await self._repost(channel, script, user=ctx.author)
        extra = f"\n-# initial sticky posted · {new_msg.jump_url}" if new_msg else ""
        return await ctx.success(
            f"Sticky set in {channel.mention}\n• {_format_trigger(message_limit, interval_seconds)}{extra}"
        )

    @stickymessage.command(
        name="edit",
        aliases=["update"],
        description="Edit a sticky's script, message limit, and/or interval",
        example=",stickymessage edit #general New text 10 10m",
        usage="[channel] <script> [message_limit] [interval]",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_edit(self, ctx, *, args: str = ""):
        channel, script, message_limit, interval_seconds = await self._resolve_add(
            ctx, args
        )
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(
                f"No sticky in {channel.mention} — use `{ctx.clean_prefix}stickymessage add` first"
            )
        await self.db.execute(
            """UPDATE sticky_message
               SET code = $1, message_limit = $2, interval_seconds = $3,
                   message_count = 0, last_sent = $4
               WHERE guild_id = $5 AND channel_id = $6""",
            script,
            message_limit,
            interval_seconds,
            _now_naive(),
            ctx.guild.id,
            channel.id,
        )
        self._msg_counts[channel.id] = 0
        await self._repost(channel, script, user=ctx.author)
        return await ctx.success(
            f"Updated sticky in {channel.mention}\n• {_format_trigger(message_limit, interval_seconds)}"
        )

    @stickymessage.command(
        name="interval",
        aliases=["changeinterval", "ci"],
        description="Change the auto-send interval for a sticky (disabled when limit is 1)",
        example=",stickymessage interval #general 10m",
        usage="[channel] <interval|off>",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_interval(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
        interval_token = None
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                rest = tokens[1:]
            except Exception:
                rest = tokens
            if rest:
                interval_token = rest[0]
        if not interval_token:
            raise CommandError(
                f"Provide an interval (e.g. `30s`, `5m`, `1h`) or `off`\n"
                f"Example: `{ctx.clean_prefix}stickymessage interval #general 10m`"
            )
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(f"No sticky in {channel.mention}")

        if interval_token.lower() in {"off", "none", "0", "disable", "disabled"}:
            seconds = _INTERVAL_DISABLED
        else:
            if not is_duration_token(interval_token):
                raise CommandError(
                    f"Provide an interval (e.g. `30s`, `5m`, `1h`) or `off`\n"
                    f"Example: `{ctx.clean_prefix}stickymessage interval #general 10m`"
                )
            seconds = parse_duration_seconds(interval_token)
            if seconds is None or seconds < 30:
                raise CommandError("Interval must be at least **30 seconds** (or `off`)")
            if int(existing.get("message_limit") or 1) <= 1:
                raise CommandError(
                    "Interval is disabled while message limit is **1** (every message).\n"
                    f"Raise the limit first: `{ctx.clean_prefix}stickymessage messagelimit {channel.mention} 5`"
                )

        await self.db.execute(
            "UPDATE sticky_message SET interval_seconds = $1 WHERE guild_id = $2 AND channel_id = $3",
            seconds,
            ctx.guild.id,
            channel.id,
        )
        if seconds:
            return await ctx.success(
                f"Sticky interval for {channel.mention} set to **{naturaldelta(seconds)}** "
                f"(`{format_duration_token(seconds)}`)"
            )
        return await ctx.success(f"Sticky interval for {channel.mention} **disabled**")

    @stickymessage.command(
        name="messagelimit",
        aliases=["changemessagelimit", "cml", "limit"],
        description="Change how many messages trigger a sticky re-post (1 = every message)",
        example=",stickymessage messagelimit #general 1",
        usage="[channel] <limit>",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_messagelimit(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
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
            raise CommandError(
                f"Provide a message limit between **1** and **100**\n"
                f"Example: `{ctx.clean_prefix}stickymessage messagelimit #general 10`"
            )
        limit = int(limit_token)
        if not 1 <= limit <= 100:
            raise CommandError("Message limit must be between **1** and **100**")
        existing = await self._get_row(ctx.guild.id, channel.id)
        if not existing:
            raise CommandError(f"No sticky in {channel.mention}")

        
        interval = int(existing.get("interval_seconds") or 0)
        if limit <= 1:
            interval = _INTERVAL_DISABLED
        elif interval < 30:
            interval = _DEFAULT_INTERVAL_SECONDS

        await self.db.execute(
            """UPDATE sticky_message
               SET message_limit = $1, interval_seconds = $2, message_count = 0
               WHERE guild_id = $3 AND channel_id = $4""",
            limit,
            interval,
            ctx.guild.id,
            channel.id,
        )
        self._msg_counts[channel.id] = 0
        return await ctx.success(
            f"Sticky for {channel.mention} → {_format_trigger(limit, interval)}"
        )

    @stickymessage.command(
        name="view",
        aliases=["preview", "show"],
        description="View the sticky message for a channel",
        example=",stickymessage view #general",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_view(self, ctx, channel: Optional[TextChannel] = None):
        channel = channel or ctx.channel  # type: ignore[assignment]
        row = await self._get_row(ctx.guild.id, channel.id)
        if not row:
            raise CommandError(f"No sticky message in {channel.mention}")
        count = self._msg_counts.get(channel.id, row.get("message_count") or 0)
        await ctx.normal(
            f"**Sticky in {channel.mention}**\n"
            f"• {_format_trigger(int(row['message_limit']), int(row['interval_seconds'] or 0))}\n"
            f"• current count: **{count}**"
        )
        return await self.bot.send_embed(ctx.channel, row["code"], user=ctx.author)

    @stickymessage.command(
        name="list",
        aliases=["ls"],
        description="View all sticky messages in this server",
        example=",stickymessage list",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_list(self, ctx):
        entries = await self.db.fetch(
            """SELECT channel_id, code,
                      COALESCE(message_limit, $2) AS message_limit,
                      COALESCE(interval_seconds, $3) AS interval_seconds
               FROM sticky_message WHERE guild_id = $1""",
            ctx.guild.id,
            _DEFAULT_MESSAGE_LIMIT,
            _INTERVAL_DISABLED,
        )
        if not entries:
            raise CommandError("No sticky messages exist")
        lines = []
        for i, e in enumerate(entries, start=1):
            ch = ctx.guild.get_channel(e["channel_id"])
            label = ch.mention if ch else f"`{e['channel_id']}`"
            lines.append(
                f"`{i}` {label} — {_format_trigger(int(e['message_limit']), int(e['interval_seconds'] or 0))}"
            )
        return await ctx.paginate(
            Embed(title="Sticky Messages", color=self.bot.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            lines,
        )

    @stickymessage.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="Remove a sticky message from a channel",
        example=",stickymessage remove #general",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_remove(self, ctx, channel: Optional[TextChannel] = None):
        channel = channel or ctx.channel  # type: ignore[assignment]
        row = await self._get_row(ctx.guild.id, channel.id)
        if not row:
            raise CommandError(f"No sticky in {channel.mention}")
        prev_id = self.pinned_ids.pop(channel.id, None) or row.get("last_message")
        if prev_id:
            with contextlib.suppress(
                discord.NotFound, discord.HTTPException, discord.Forbidden
            ):
                await self.bot.http.delete_message(channel.id, prev_id)
        await self.db.execute(
            "DELETE FROM sticky_message WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        self._msg_counts.pop(channel.id, None)
        self._last_activity.pop(channel.id, None)
        self._pending_repost.discard(channel.id)
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
        return await self.stickymessage_interval.callback(self, ctx, args=args)

    @stickymessage_change.command(
        name="messagelimit",
        aliases=["limit", "cml", "changemessagelimit"],
        description="Change sticky message limit",
        example=",stickymessage change messagelimit #general 10",
        usage="[channel] <limit>",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_change_messagelimit(self, ctx, *, args: str = ""):
        return await self.stickymessage_messagelimit.callback(self, ctx, args=args)

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
        self._ensure_runtime()
        row = await self._get_row(ctx.guild.id, channel.id)
        if not row:
            return
        last_id = self.pinned_ids.get(channel.id) or row.get("last_message")
        if getattr(ctx.message, "id", None) and last_id and ctx.message.id == last_id:
            return
        self._msg_counts[channel.id] = self._msg_counts.get(channel.id, 0) + 1
        self._last_activity[channel.id] = _now_naive()
        count = self._msg_counts[channel.id]
        limit = max(1, int(row["message_limit"] or _DEFAULT_MESSAGE_LIMIT))
        with contextlib.suppress(Exception):
            await self.db.execute(
                "UPDATE sticky_message SET message_count = $1 WHERE guild_id = $2 AND channel_id = $3",
                count,
                ctx.guild.id,
                channel.id,
            )
        if count >= limit:
            
            self._enqueue_repost(
                ctx.guild.id, channel.id, row["code"], user=ctx.author
            )

    @tasks.loop(seconds=30.0)
    async def _sticky_interval_loop(self) -> None:
        """Re-post sticky when there was activity but the message limit wasn't hit.

        Skipped entirely when interval_seconds is 0 (every-message mode).
        """
        if getattr(self.db, "pool", None) is None:
            return
        try:
            rows = await self.db.fetch(
                """SELECT guild_id, channel_id, code,
                          COALESCE(interval_seconds, 0) AS interval_seconds,
                          COALESCE(message_count, 0) AS message_count,
                          COALESCE(message_limit, 1) AS message_limit,
                          last_sent
                   FROM sticky_message
                   WHERE COALESCE(interval_seconds, 0) >= 30
                     AND COALESCE(message_limit, 1) > 1"""
            )
        except Exception:
            return
        now = _now_naive()
        for row in rows:
            try:
                interval = int(row["interval_seconds"] or 0)
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
                self._enqueue_repost(row["guild_id"], channel_id, row["code"])
            except Exception:
                continue

    @_sticky_interval_loop.before_loop
    async def _before_sticky_interval_loop(self) -> None:
        await self.bot.wait_until_ready()
