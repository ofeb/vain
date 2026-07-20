from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group
from core.managers.values import color
from core.managers.permissions import has_permissions
from core.tools.moderation_args import (
    is_duration_token,
    parse_duration_seconds,
)

from .events import GiveawayEvents
from .views import build_giveaway_panel


_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def _clean_token(token: str) -> str:
    return _INVISIBLE_RE.sub("", (token or "")).strip()

def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def panel_embed(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description or None, url=url)
    if title:
        embed.title = title
    if author:
        if author_icon:
            embed.set_author(name=author, icon_url=author_icon)
        else:
            embed.set_author(name=author)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed



if TYPE_CHECKING:
    from typing import List


def shorten(text: str, length: int):
    return text[:length] + "..." if len(text) > length else text


def _parse_duration_value(argument: str) -> int | None:
    """Parse a duration token into seconds, or None if invalid/unparseable."""
    raw = _clean_token(argument).lower()
    if not raw:
        return None
    if raw.isdigit():
        seconds = int(raw)
    else:
        seconds = parse_duration_seconds(raw)
    if seconds is None or seconds <= 0:
        return None
    return seconds


class DurationSeconds(commands.Converter):
    """Accept raw seconds or human tokens like ``1h``, ``30m``, ``2d``."""

    async def convert(self, ctx: Context, argument: str) -> int:
        cleaned = _clean_token(argument)
        seconds = _parse_duration_value(cleaned)
        if seconds is None:
            shown = cleaned or (argument or "").strip() or "empty"
            if len(shown) > 40:
                shown = shown[:37] + "..."
            raise commands.BadArgument(
                f"Could not parse duration **{shown}**. Use e.g. `30s`, `10m`, `1h`, `2d`."
            )
        if seconds > 365 * 86400:
            raise commands.BadArgument("Duration cannot exceed **1 year**.")
        return seconds


async def _resolve_channel(ctx: Context, token: str) -> discord.abc.Messageable | None:
    """Resolve channel by mention, id, or name (``txt``, ``#txt``, mangled paste)."""
    from core.tools.convert.channel import resolve_channel

    ch = await resolve_channel(ctx, token, text_only=True, allow_threads=True)
    if ch is not None:
        return ch  # type: ignore[return-value]
    return None


async def _parse_start_args(
    ctx: Context, raw: str
) -> tuple[discord.abc.Messageable, int, int, str]:
    """Parse ``[channel] <duration> [winners] <prize>``.

    Examples:
    - ``2m 1 Nitro Classic``
    - ``#giveaways 1h 2 Nitro``
    - ``1h Nitro`` (defaults to 1 winner)
    """
    tokens = [_clean_token(t) for t in (raw or "").split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise commands.BadArgument(
            "Usage: `,giveaway start [channel] <duration> [winners] <prize>` "
            "e.g. `,giveaway start 2m 1 Nitro`"
        )

    channel: discord.abc.Messageable = ctx.channel
    i = 0

    
    maybe_channel = await _resolve_channel(ctx, tokens[0])
    if maybe_channel is not None:
        channel = maybe_channel
        i = 1
    elif is_duration_token(tokens[0]) or (
        tokens[0].isdigit() and len(tokens) >= 2
    ):
        i = 0
    else:
        
        
        dur_at = next(
            (idx for idx in range(len(tokens)) if is_duration_token(tokens[idx])),
            None,
        )
        if dur_at is None:
            raise commands.BadArgument(
                f"**{tokens[0]}** is not a channel or duration. "
                "Usage: `,giveaway start [channel] <duration> [winners] <prize>` "
                "e.g. `,giveaway start #chat 2m 1 Nitro`"
            )
        i = dur_at

    if i >= len(tokens):
        raise commands.BadArgument(
            "Missing duration. Use e.g. `30s`, `10m`, `1h`, `2d`."
        )

    seconds = _parse_duration_value(tokens[i])
    if seconds is None:
        raise commands.BadArgument(
            f"Could not parse duration **{tokens[i]}**. Use e.g. `30s`, `10m`, `1h`, `2d`."
        )
    if seconds > 365 * 86400:
        raise commands.BadArgument("Duration cannot exceed **1 year**.")
    i += 1

    winners = 1
    if i < len(tokens) and tokens[i].isdigit():
        winners = int(tokens[i])
        i += 1

    prize = " ".join(tokens[i:]).strip()
    if not prize:
        raise commands.BadArgument(
            "A prize is required. Example: `,giveaway start 2m 1 Nitro Classic`"
        )
    if winners < 1:
        raise commands.BadArgument("Winner count must be at least **1**")

    return channel, seconds, winners, prize


class Giveaway(commands.Cog):
    """Giveaway management system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_requirements(self, record) -> list[str]:
        r: list[str] = []
        if record.get("max_level"):
            r.append(f"max level **{record['max_level']}**")
        if record.get("min_level"):
            r.append(f"min level **{record['min_level']}**")
        if record.get("required_roles"):
            for role_id in record["required_roles"] or []:
                r.append(f"role <@&{role_id}>")
        return r

    def _events(self) -> GiveawayEvents | None:
        return self.bot.get_cog("GiveawayEvents")  # type: ignore[return-value]

    async def _resolve_giveaway_message(
        self,
        ctx: Context,
        ref: str | None = None,
    ) -> discord.Message | None:
        """Resolve a giveaway message from reply, jump link, or id."""
        
        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                return await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except (discord.NotFound, discord.HTTPException):
                pass

        if not ref:
            return None
        raw = str(ref).strip()

        
        m = re.search(
            r"(?:https?://)?(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/"
            r"(\d+)/(\d+)/(\d+)",
            raw,
        )
        if m:
            guild_id, channel_id, message_id = map(int, m.groups())
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    channel = None
            if channel is not None:
                try:
                    return await channel.fetch_message(message_id)
                except Exception:
                    return None
            return None

        
        if raw.isdigit() and 15 <= len(raw) <= 20:
            message_id = int(raw)
            try:
                return await ctx.channel.fetch_message(message_id)
            except (discord.NotFound, discord.HTTPException):
                pass
            row = await self.bot.db.fetchrow(
                "SELECT channel_id FROM giveaways WHERE message_id = $1",
                message_id,
            )
            if row:
                channel = self.bot.get_channel(int(row["channel_id"]))
                if channel is not None:
                    try:
                        return await channel.fetch_message(message_id)
                    except Exception:
                        return None
        return None

    def _host_mention(self, record, fallback: discord.abc.User | None = None) -> str:
        hosts = record.get("hosts") or []
        if hosts:
            return f"<@{int(hosts[0])}>"
        if fallback is not None:
            return fallback.mention
        return "unknown"

    def _panel(
        self,
        *,
        message_id: int,
        prize: str,
        end_time: datetime,
        winners: int,
        host: str,
        entries: int = 0,
        guild: discord.Guild | None = None,
        ended: bool = False,
        winner_mentions: str | None = None,
        no_entries: bool = False,
    ):
        icon = str(guild.icon.url) if guild and guild.icon else None
        return build_giveaway_panel(
            message_id=message_id,
            prize=prize,
            end_time=end_time,
            winners=winners,
            host_mention=host,
            entries=entries,
            guild_icon=icon,
            ended=ended,
            winner_mentions=winner_mentions,
            no_entries=no_entries,
        )

    @group(
        name="giveaway",
        description="Start a giveaway quickly and easily",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def giveaway(self, ctx: Context) -> None:
        """Giveaway management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway.command(
        name="reroll",
        description="Reroll winners for an ended giveaway",
        guild_only=True,
        usage="[message id/link] [winners]",
        example=",giveaway reroll 123456789012345678",
    )
    @describe(
        target="Message id, jump link, or leave blank to use a reply",
        winners="How many winners to pick (default 1)",
    )
    @has_permissions(manage_guild=True)
    async def reroll(
        self,
        ctx: Context,
        target: str = None,
        winners: int = 1,
    ) -> None:
        """Reroll winners. Reply to the giveaway, or pass a message id/link.

        Examples:
        - reply to the giveaway: `,giveaway reroll`
        - `,giveaway reroll 123456789012345678`
        - `,giveaway reroll https://discord.com/channels/.../.../...`
        - `,giveaway reroll 123… 2` (2 winners)
        """
        
        winners_count = winners
        ref = target
        if target and target.isdigit() and len(target) < 15 and ctx.message.reference:
            winners_count = max(1, int(target))
            ref = None
        elif target and " " in target:
            parts = target.split()
            if parts[-1].isdigit() and len(parts[-1]) < 15:
                winners_count = max(1, int(parts[-1]))
                ref = " ".join(parts[:-1]) or None

        message = await self._resolve_giveaway_message(ctx, ref)
        if not message:
            await ctx.warn(
                "Reply to a giveaway, or pass a **message id** / **jump link**."
            )
            return

        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        if not giveaway.get("win_message_id"):
            await ctx.warn("That giveaway **isn't over** yet")
            return
        if winners_count < 1:
            await ctx.warn("Winner count must be at least **1**")
            return

        events = self._events()
        if events is None:
            await ctx.warn("Giveaway events are not loaded")
            return

        new_winners = await events.reroll_giveaway(
            dict(giveaway),
            winners_count=winners_count,
            channel=message.channel,
        )
        if not new_winners:
            await ctx.warn("No valid entries to reroll")
            return
        await ctx.message.add_reaction("👍")

    @giveaway.command(
        name="end",
        description="End an active giveaway early",
        guild_only=True,
        usage="[message id/link]",
        example=",giveaway end",
    )
    @describe(target="Message id, jump link, or leave blank to use a reply")
    @has_permissions(manage_guild=True)
    async def end(self, ctx: Context, *, target: str = None) -> None:
        """End an active giveaway early (reply or message id/link)."""
        message = await self._resolve_giveaway_message(ctx, target)
        if not message:
            await ctx.warn(
                "Reply to a giveaway, or pass a **message id** / **jump link**."
            )
            return

        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        if giveaway.get("win_message_id"):
            await ctx.warn("That giveaway has **already ended**")
            return

        events = self._events()
        if events is None:
            await ctx.warn("Giveaway events are not loaded")
            return
        await events.end_giveaway(dict(giveaway), force=True)
        await ctx.message.add_reaction("👍")

    @giveaway.group(
        name="edit",
        description="Edit options and limits for a specific giveaway",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def giveaway_edit(self, ctx: Context) -> None:
        """Giveaway edit management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway_edit.command(
        name="maxlevel",
        description="Set the maximum level requirement for giveaway entry",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", level="Maximum level required")
    @has_permissions(manage_guild=True)
    async def giveaway_edit_maxlevel(
        self,
        ctx: Context,
        message: discord.Message = None,
        level: int = 1,
    ) -> None:
        """Set the maximum level requirement for giveaway entry."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        try:
            await self.bot.db.execute(
                "UPDATE giveaways SET max_level = $1 WHERE message_id = $2",
                level,
                message.id,
            )
        except Exception:
            await ctx.warn("That is not a giveaway")
            return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        events = self._events()
        if events:
            await events.rebuild_panel_message(
                message,
                dict(giveaway),
                ended=bool(giveaway.get("win_message_id")),
            )
        await ctx.message.add_reaction("👍")

    @giveaway_edit.command(
        name="prize",
        description="Change prize for a giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", prize="New prize name")
    @has_permissions(manage_guild=True)
    async def giveaway_edit_prize(
        self,
        ctx: Context,
        message: discord.Message = None,
        prize: str = None,
    ) -> None:
        """Change prize for a giveaway."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return

        if not prize:
            await ctx.warn("A prize is required")
            return

        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return

        await self.bot.db.execute(
            "UPDATE giveaways SET prize = $1 WHERE message_id = $2",
            prize,
            message.id,
        )
        giveaway = dict(giveaway)
        giveaway["prize"] = prize
        events = self._events()
        if events:
            await events.rebuild_panel_message(
                message,
                giveaway,
                ended=bool(giveaway.get("win_message_id")),
            )
        await ctx.message.add_reaction("👍")

    @giveaway_edit.command(
        name="duration",
        description="Change the end date for a giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", duration="Duration like 1h, 30m, or seconds")
    @has_permissions(manage_guild=True)
    async def giveaway_edit_duration(
        self,
        ctx: Context,
        message: discord.Message = None,
        duration: DurationSeconds = None,
    ) -> None:
        """Change the end date for a giveaway."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return

        if not duration:
            await ctx.warn("A duration is required (e.g. `1h`, `30m`, `2d`)")
            return

        
        secs = int(duration)
        end_time = datetime.now() + timedelta(seconds=secs)
        try:
            await self.bot.db.execute(
                "UPDATE giveaways SET expiration = $1 WHERE message_id = $2",
                end_time,
                message.id,
            )
        except Exception:
            await ctx.warn("That is not a giveaway")
            return

        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        giveaway = dict(giveaway)
        giveaway["expiration"] = end_time
        events = self._events()
        if events:
            await events.rebuild_panel_message(
                message,
                giveaway,
                ended=bool(giveaway.get("win_message_id")),
            )
            if not giveaway.get("win_message_id"):
                events.schedule_end(message.id, delay_seconds=float(secs))
        await ctx.success(
            f"Expiration set to {discord.utils.format_dt(end_time, style='R')}"
        )

    @giveaway.command(
        name="start",
        description="Start a new giveaway",
        guild_only=True,
        usage="[channel] <duration> [winners] <prize>",
        example=",giveaway start 30s 1 nitro",
    )
    @describe(
        arguments="[channel] <duration> [winners] <prize> — e.g. 30s 1 Nitro or #chat 1h 2 Nitro",
    )
    @has_permissions(manage_guild=True)
    async def start(self, ctx: Context, *, arguments: str = None) -> None:
        """Start a new giveaway.

        Syntax: `,giveaway start [channel] <duration> [winners] <prize>`

        Examples:
        - `,giveaway start 30s 1 nitro`
        - `,giveaway start 1h 1 Nitro Classic`
        - `,giveaway start #giveaways 1h 2 Nitro`
        """
        if not arguments or not str(arguments).strip():
            await ctx.warn(
                "Usage: `,giveaway start [channel] <duration> [winners] <prize>` "
                "e.g. `,giveaway start 30s 1 Nitro`"
            )
            return

        try:
            channel, seconds, winners, prize = await _parse_start_args(ctx, arguments)
        except commands.BadArgument as exc:
            await ctx.warn(str(exc))
            return

        
        end_time = datetime.now() + timedelta(seconds=seconds)

        panel = self._panel(
            message_id=0,
            prize=prize,
            end_time=end_time,
            winners=winners,
            host=ctx.author.mention,
            entries=0,
            guild=ctx.guild,
        )
        message = await channel.send(view=panel)

        panel = self._panel(
            message_id=message.id,
            prize=prize,
            end_time=end_time,
            winners=winners,
            host=ctx.author.mention,
            entries=0,
            guild=ctx.guild,
        )

        async def _edit() -> None:
            try:
                await message.edit(view=panel)
            except Exception:
                pass

        async def _insert() -> None:
            await self.bot.db.execute(
                """
                INSERT INTO giveaways (
                    guild_id, channel_id, message_id, prize, expiration,
                    winner_count, hosts, entries, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (message_id) DO UPDATE SET
                    prize = EXCLUDED.prize,
                    expiration = EXCLUDED.expiration,
                    winner_count = EXCLUDED.winner_count,
                    hosts = EXCLUDED.hosts,
                    entries = EXCLUDED.entries,
                    win_message_id = NULL
                """,
                ctx.guild.id,
                channel.id,
                message.id,
                prize,
                end_time,
                winners,
                [ctx.author.id],
                [],
                datetime.now(),
            )

        await asyncio.gather(_edit(), _insert())

        events = self._events()
        if events:
            
            events.schedule_end(message.id, delay_seconds=float(seconds))

        try:
            await ctx.message.add_reaction("👍")
        except Exception:
            await ctx.success(f"Giveaway started in {channel.mention}")

    @giveaway.group(
        name="dmonwin",
        aliases=["dmonswin"],
        invoke_without_command=True,
        description="Toggle or configure DMs when someone wins a giveaway",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def dmonwin(self, ctx: Context, state: str = None) -> None:
        """`,giveaway dmonwin on|off` or subcommands."""
        events = self._events()
        if events is None:
            await ctx.warn("Giveaway events are not loaded")
            return
        if state is None:
            settings = await events.get_settings(ctx.guild.id)
            on = settings.get("dm_on_win", True)
            await ctx.success(
                f"DM on win is **{'on' if on else 'off'}**"
                + (" · custom script set" if settings.get("dm_script") else "")
            )
            return
        low = state.lower().strip()
        if low in {"on", "enable", "true", "yes", "1"}:
            await events.set_dm_on_win(ctx.guild.id, True)
            await ctx.success("Winners will be **DM'd** when they win")
            return
        if low in {"off", "disable", "false", "no", "0"}:
            await events.set_dm_on_win(ctx.guild.id, False)
            await ctx.success("Winners will **not** be DM'd (channel announce only)")
            return
        await ctx.warn("Use `on` or `off`, or `,giveaway dmonwin script ...`")

    @dmonwin.command(name="on", description="Enable DMing winners")
    @has_permissions(manage_guild=True)
    async def dmonwin_on(self, ctx: Context) -> None:
        events = self._events()
        if not events:
            return
        await events.set_dm_on_win(ctx.guild.id, True)
        await ctx.success("Winners will be **DM'd** when they win")

    @dmonwin.command(name="off", description="Disable DMing winners")
    @has_permissions(manage_guild=True)
    async def dmonwin_off(self, ctx: Context) -> None:
        events = self._events()
        if not events:
            return
        await events.set_dm_on_win(ctx.guild.id, False)
        await ctx.success("Winners will **not** be DM'd")

    @dmonwin.command(
        name="script",
        aliases=["message", "msg", "template"],
        description="Set a custom DM script for winners",
        usage="[script|clear]",
        example=",giveaway dmonwin script {embed}$v{title: You won!}$v{description: **{prize}** in {guild.name}}",
    )
    @has_permissions(manage_guild=True)
    async def dmonwin_script(self, ctx: Context, *, script: str = None) -> None:
        """Customize the winner DM (embed script syntax). Use `clear` to reset."""
        events = self._events()
        if not events:
            await ctx.warn("Giveaway events are not loaded")
            return
        if not script or not script.strip():
            settings = await events.get_settings(ctx.guild.id)
            current = settings.get("dm_script")
            if current:
                await ctx.send(f"```\n{current[:1900]}\n```")
            else:
                await ctx.success("Using the **default** winner DM script")
            return
        if script.strip().lower() in {"clear", "reset", "default", "none", "remove"}:
            await events.set_dm_script(ctx.guild.id, None)
            await ctx.success("Winner DM script **reset** to default")
            return
        await events.set_dm_script(ctx.guild.id, script.strip())
        await ctx.success("Updated **winner DM** script")


async def setup(bot: commands.Bot):
    """Load the Giveaway cog + events."""
    await bot.add_cog(Giveaway(bot))
    await bot.add_cog(GiveawayEvents(bot))
