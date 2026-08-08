from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group
from config import color
from core.managers.permissions import has_permissions
from core.tools.moderation_args import (
    is_duration_token,
    parse_duration_seconds,
)

from .events import GiveawayEvents
from .proper.requirements import (
    apply_start_flags,
    catalog_lines,
    empty_requirements,
    format_requirements,
    has_any_requirement,
    split_start_payload,
)
from .proper.views import build_giveaway_panel

_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_COMMA_DURATION = re.compile(
    r"^(?P<head>.*?)\s*,\s*(?P<dur>\d+\s*[smhdw](?:econds?|inutes?|ours?|ays?|eeks?)?|\d+)\s*$",
    re.I,
)

def _clean_token(token: str) -> str:
    return _INVISIBLE_RE.sub("", (token or "")).strip()

if TYPE_CHECKING:
    from typing import List

def shorten(text: str, length: int):
    return text[:length] + "..." if len(text) > length else text

_WORD_DURATION = re.compile(
    r"^(?P<n>\d+)\s*(?P<u>"
    r"s(?:ec(?:ond)?s?)?|"
    r"m(?:in(?:ute)?s?)?|"
    r"h(?:(?:ou)?rs?)?|"
    r"d(?:ays?)?|"
    r"w(?:eeks?)?|"
    r"y(?:ears?)?"
    r")$",
    re.I,
)


def _parse_duration_value(argument: str) -> int | None:
    """Parse a duration token into seconds, or None if invalid/unparseable.

    Accepts ``30s``, ``10m``, ``2h``, ``2 hours``, ``1 day``, raw seconds.
    """
    raw = _clean_token(argument).lower().strip()
    if not raw:
        return None
    if raw.isdigit():
        seconds = int(raw)
        return seconds if seconds > 0 else None
    
    seconds = parse_duration_seconds(raw.replace(" ", ""))
    if seconds is not None and seconds > 0:
        return seconds
    m = _WORD_DURATION.match(raw.replace(" ", ""))
    if not m:
        m = _WORD_DURATION.match(raw)
    if m:
        n = int(m.group("n"))
        u = m.group("u")[0].lower()
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
        seconds = n * mult[u]
        return seconds if seconds > 0 else None
    return None

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
                f"Couldn\u2019t read duration **{shown}**. Try `30s`, `10m`, `1h`, or `2d`."
            )
        if seconds > 365 * 86400:
            raise commands.BadArgument("Duration can\u2019t be longer than **1 year**.")
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
) -> tuple[discord.abc.Messageable, int, int, str, dict]:
    """Parse start body + optional ``--winners`` / ``--requirement`` flags.

    Supported shapes:
    - ``#channel Prize, 2 hours``
    - ``#channel Prize, 2 hours --winners 3``
    - ``#channel Prize, 2h --requirement level 5, badge``
    - legacy: ``[channel] <duration> [winners] <prize>``
    """
    body, flag_chunks = split_start_payload(raw or "")
    winners_flag, requirements = await apply_start_flags(ctx, flag_chunks)

    text = body.strip()
    if not text:
        raise commands.BadArgument(
            "Usage: `,giveaway start [channel] <prize>, <duration>` "
            "\u00b7 add `--winners 3` or `--requirement level 5`"
        )

    channel: discord.abc.Messageable = ctx.channel
    tokens = [_clean_token(t) for t in text.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise commands.BadArgument(
            "Usage: `,giveaway start [channel] <prize>, <duration>`"
        )

    
    maybe_channel = await _resolve_channel(ctx, tokens[0])
    prize_duration = text
    if maybe_channel is not None:
        channel = maybe_channel
        prize_duration = " ".join(tokens[1:]).strip()

    seconds: int | None = None
    prize = ""
    winners = 1

    
    m = _COMMA_DURATION.match(prize_duration.strip())
    if m:
        prize = m.group("head").strip().strip(",")
        seconds = _parse_duration_value(m.group("dur"))
        if seconds is None:
            raise commands.BadArgument(
                f"Couldn\u2019t read duration **{m.group('dur')}**. Try `2h` or `2 hours`."
            )
    else:
        
        parts = [_clean_token(t) for t in prize_duration.split() if _clean_token(t)]
        if not parts:
            raise commands.BadArgument(
                "Include a prize and duration. Example: "
                "`,giveaway start #chat Nitro, 2 hours`"
            )

        
        if is_duration_token(parts[0]) or (
            parts[0].isdigit() and len(parts) >= 2 and _parse_duration_value(parts[0])
        ):
            seconds = _parse_duration_value(parts[0])
            i = 1
            if i < len(parts) and parts[i].isdigit() and len(parts[i]) < 6:
                winners = int(parts[i])
                i += 1
            prize = " ".join(parts[i:]).strip()
        else:
            
            seconds = _parse_duration_value(parts[-1])
            if seconds is not None:
                prize = " ".join(parts[:-1]).strip().rstrip(",")
            else:
                
                dur_at = next(
                    (
                        idx
                        for idx, p in enumerate(parts)
                        if is_duration_token(p) or _parse_duration_value(p)
                    ),
                    None,
                )
                if dur_at is None:
                    raise commands.BadArgument(
                        "Missing duration. Example: `,giveaway start Nitro, 2 hours`"
                    )
                seconds = _parse_duration_value(parts[dur_at])
                prize = " ".join(parts[:dur_at] + parts[dur_at + 1 :]).strip().rstrip(",")

    if seconds is None or seconds <= 0:
        raise commands.BadArgument(
            "Couldn\u2019t read the duration. Try `30s`, `10m`, `2h`, or `2 hours`."
        )
    if seconds > 365 * 86400:
        raise commands.BadArgument("Duration can\u2019t be longer than **1 year**.")
    if not prize:
        raise commands.BadArgument(
            "A prize is required. Example: `,giveaway start #chat Nitro, 2 hours`"
        )
    if winners_flag is not None:
        winners = winners_flag
    if winners < 1:
        raise commands.BadArgument("Winner count must be at least **1**.")

    return channel, seconds, winners, prize, requirements

class Giveaway(commands.Cog):
    """Giveaway management system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_requirements(self, record, guild: discord.Guild | None = None) -> list[str]:
        return format_requirements(record or {}, guild=guild)

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
        settings: dict | None = None,
        requirements: dict | None = None,
    ):
        icon = str(guild.icon.url) if guild and guild.icon else None
        settings = settings or {}
        req_lines = (
            format_requirements(requirements or {}, guild=guild)
            if has_any_requirement(requirements or {})
            else []
        )
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
            button_label=settings.get("button_label"),
            button_emoji=settings.get("button_emoji"),
            show_entries=bool(settings.get("show_entries", True)),
            join_type=str(settings.get("join_type") or "button"),
            requirement_lines=req_lines,
        )

    @group(
        name="giveaway",
        aliases=["gw"],
        description="Run giveaways with optional entry rules",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def giveaway(self, ctx: Context) -> None:
        """Giveaway management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway.command(
        name="requirements",
        aliases=["reqs", "requirement"],
        description="List every entry rule you can attach to a giveaway",
        guild_only=True,
        example=",giveaway requirements",
    )
    @has_permissions(manage_guild=True)
    async def giveaway_requirements(self, ctx: Context) -> None:
        """Show all supported entry requirements with plain-English explanations."""
        lines = catalog_lines()
        header = (
            "**Giveaway entry rules**\n"
            "-# Attach with `--requirement …` on `,giveaway start`\n"
            "-# Combine several: `--requirement level 5, badge`\n"
            "-# Winners flag: `--winners 3`\n"
        )
        body = "\n".join(lines)
        examples = (
            "\n\n**Examples**\n"
            "```\n"
            ",giveaway start #chat Nitro, 2 hours\n"
            ",giveaway start #chat Nitro, 2 hours --winners 3\n"
            ",giveaway start #chat Nitro, 2 hours --requirement level 5\n"
            ",giveaway start #chat Nitro, 2h --requirement level 5, badge\n"
            ",giveaway start #chat Nitro, 1d --requirement role Members --requirement invites 3\n"
            "```"
        )
        
        text = header + "\n" + body + examples
        if len(text) > 3800:
            embed = discord.Embed(
                color=color.base,
                title="Giveaway entry rules",
                description=header,
            )
            await ctx.paginate(embed, [f"`{i:02d}` " + ln.split(" — ", 1)[-1] if " — " in ln else ln for i, ln in enumerate(lines, 1)])
            return
        emb = discord.Embed(color=color.base, description=text)
        await ctx.send(embed=emb)

    @giveaway.command(
        name="reroll",
        aliases=["rr"],
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
        aliases=["e", "stop"],
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
        aliases=["ed"],
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
        aliases=["ml"],
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
        aliases=["p"],
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
        aliases=["d"],
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
        aliases=["s", "create", "launch"],
        description="Launch a giveaway in a channel",
        guild_only=True,
        usage="[channel] <prize>, <duration> [--winners n] [--requirement …]",
        example=",giveaway start #chat Nitro, 2 hours --requirement level 5",
    )
    @describe(
        arguments=(
            "[channel] <prize>, <duration> · optional --winners / --requirement flags"
        ),
    )
    @has_permissions(manage_guild=True)
    async def start(self, ctx: Context, *, arguments: str = None) -> None:
        """Launch a giveaway.

        Preferred:
        - `,giveaway start #chat Nitro, 2 hours`
        - `,giveaway start #chat Nitro, 2 hours --winners 3`
        - `,giveaway start #chat Nitro, 2h --requirement level 5, badge`

        See `,giveaway requirements` for every entry rule.
        """
        if not arguments or not str(arguments).strip():
            await ctx.warn(
                "Usage: `,giveaway start [channel] <prize>, <duration>`\n"
                "-# e.g. `,giveaway start #chat Nitro, 2 hours --winners 3`\n"
                "-# rules: `,giveaway requirements`"
            )
            return

        try:
            channel, seconds, winners, prize, requirements = await _parse_start_args(
                ctx, arguments
            )
        except commands.BadArgument as exc:
            await ctx.warn(str(exc))
            return

        end_time = datetime.now() + timedelta(seconds=seconds)
        requirements = requirements or empty_requirements()

        events = self._events()
        settings = await events.get_settings(ctx.guild.id) if events else {}

        panel = self._panel(
            message_id=0,
            prize=prize,
            end_time=end_time,
            winners=winners,
            host=ctx.author.mention,
            entries=0,
            guild=ctx.guild,
            settings=settings,
            requirements=requirements,
        )
        message = await channel.send(view=panel)

        join_type = str(settings.get("join_type") or "button").lower()
        if join_type == "reaction":
            react = settings.get("join_reaction") or "🎉"
            try:
                await message.add_reaction(react)
            except Exception:
                with contextlib.suppress(Exception):
                    await message.add_reaction("🎉")

        panel = self._panel(
            message_id=message.id,
            prize=prize,
            end_time=end_time,
            winners=winners,
            host=ctx.author.mention,
            entries=0,
            guild=ctx.guild,
            settings=settings,
            requirements=requirements,
        )

        async def _edit() -> None:
            try:
                await message.edit(view=panel)
            except Exception:
                pass

        async def _insert() -> None:
            import json

            min_level = requirements.get("min_level")
            roles = list(requirements.get("required_roles") or []) or None
            req_json = {
                k: v
                for k, v in requirements.items()
                if v not in (None, False, [], {})
            }
            payload = (
                ctx.guild.id,
                channel.id,
                message.id,
                prize,
                end_time,
                winners,
                [ctx.author.id],
                [],
                min_level,
                roles,
                datetime.now(),
            )
            inserted = False
            
            for req_arg in (req_json, json.dumps(req_json)):
                try:
                    await self.bot.db.execute(
                        """
                        INSERT INTO giveaways (
                            guild_id, channel_id, message_id, prize, expiration,
                            winner_count, hosts, entries, min_level, required_roles,
                            requirements, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11::jsonb, $12
                        )
                        ON CONFLICT (message_id) DO UPDATE SET
                            prize = EXCLUDED.prize,
                            expiration = EXCLUDED.expiration,
                            winner_count = EXCLUDED.winner_count,
                            hosts = EXCLUDED.hosts,
                            entries = EXCLUDED.entries,
                            min_level = EXCLUDED.min_level,
                            required_roles = EXCLUDED.required_roles,
                            requirements = EXCLUDED.requirements,
                            win_message_id = NULL
                        """,
                        *payload[:10],
                        req_arg,
                        payload[10],
                    )
                    inserted = True
                    break
                except Exception:
                    continue
            if not inserted:
                await self.bot.db.execute(
                    """
                    INSERT INTO giveaways (
                        guild_id, channel_id, message_id, prize, expiration,
                        winner_count, hosts, entries, min_level, required_roles,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (message_id) DO UPDATE SET
                        prize = EXCLUDED.prize,
                        expiration = EXCLUDED.expiration,
                        winner_count = EXCLUDED.winner_count,
                        hosts = EXCLUDED.hosts,
                        entries = EXCLUDED.entries,
                        min_level = EXCLUDED.min_level,
                        required_roles = EXCLUDED.required_roles,
                        win_message_id = NULL
                    """,
                    *payload,
                )

        await asyncio.gather(_edit(), _insert())

        if events:
            events.schedule_end(message.id, delay_seconds=float(seconds))

        try:
            await ctx.message.add_reaction("👍")
        except Exception:
            bits = [f"live in {getattr(channel, 'mention', channel)}"]
            if has_any_requirement(requirements):
                bits.append(
                    "rules: "
                    + ", ".join(format_requirements(requirements, guild=ctx.guild)[:4])
                )
            await ctx.success(" · ".join(bits))

    
    
    

    @giveaway.group(
        name="customize",
        aliases=["custom", "cfg", "config"],
        invoke_without_command=True,
        description="Customize giveaway embeds, join method, buttons, and DM-on-win",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def giveaway_customize(self, ctx: Context) -> None:
        events = self._events()
        if not events:
            await ctx.warn("Giveaway events are not loaded")
            return
        s = await events.get_settings(ctx.guild.id)
        lines = [
            f"**DM on win:** `{'on' if s.get('dm_on_win') else 'off'}` (default off)",
            f"**Join type:** `{s.get('join_type') or 'button'}`"
            + (
                f" · reaction `{s.get('join_reaction') or '🎉'}`"
                if (s.get("join_type") or "") == "reaction"
                else ""
            ),
            f"**Button:** `{s.get('button_label') or 'Enter'}` "
            f"`{s.get('button_emoji') or '🎉'}`",
            f"**Show entries:** `{'on' if s.get('show_entries', True) else 'off'}`",
            f"**Embed script:** `{'set' if s.get('embed_script') else 'default'}`",
            f"**DM script:** `{'set' if s.get('dm_script') else 'default'}`",
            "",
            "Subcommands: `embed` · `join` · `button` · `showentries` · `dmonwin`",
        ]
        await ctx.success("\n".join(lines))

    @giveaway_customize.command(
        name="embed",
        aliases=["panel", "message", "script"],
        description="Set a custom giveaway panel embed/script",
        usage="[script|clear]",
        example=",giveaway customize embed {title: {prize}}$v{description: Ends soon · hosted by {host}}",
    )
    @has_permissions(manage_guild=True)
    async def customize_embed(self, ctx: Context, *, script: str = None) -> None:
        events = self._events()
        if not events:
            return
        if not script or not script.strip():
            s = await events.get_settings(ctx.guild.id)
            cur = s.get("embed_script")
            if cur:
                await ctx.send(f"```\n{cur[:1900]}\n```")
            else:
                await ctx.success("Using the **default** giveaway panel")
            return
        if script.strip().lower() in {"clear", "reset", "default", "none", "remove"}:
            await events.update_settings(ctx.guild.id, embed_script=None)
            await ctx.success("Giveaway panel script **reset** to default")
            return
        await events.update_settings(ctx.guild.id, embed_script=script.strip())
        await ctx.success("Updated **giveaway panel** script")

    @giveaway_customize.group(
        name="join",
        aliases=["joinmethod"],
        invoke_without_command=True,
        description="Configure how users join giveaways (button or reaction)",
    )
    @has_permissions(manage_guild=True)
    async def customize_join(self, ctx: Context, join_type: str = None) -> None:
        events = self._events()
        if not events:
            return
        if join_type is None:
            s = await events.get_settings(ctx.guild.id)
            await ctx.success(
                f"Join type is **{s.get('join_type') or 'button'}**"
                + (
                    f" · reaction `{s.get('join_reaction') or '🎉'}`"
                    if (s.get("join_type") or "") == "reaction"
                    else ""
                )
            )
            return
        low = join_type.lower().strip()
        if low in {"button", "btn", "buttons"}:
            await events.update_settings(ctx.guild.id, join_type="button")
            await ctx.success("Giveaways now use a **button** to join")
            return
        if low in {"reaction", "react", "emoji"}:
            await events.update_settings(ctx.guild.id, join_type="reaction")
            await ctx.success(
                "Giveaways now use a **reaction** to join "
                "(set emoji with `,giveaway customize join reaction`)"
            )
            return
        await ctx.warn("Use `button` or `reaction`")

    @customize_join.command(
        name="type",
        aliases=["method"],
        description="Set join type to button or reaction",
    )
    @has_permissions(manage_guild=True)
    async def customize_join_type(self, ctx: Context, join_type: str) -> None:
        await self.customize_join(ctx, join_type)

    @customize_join.command(
        name="reaction",
        aliases=["emoji", "react", "joinreaction"],
        description="Set the reaction emoji used to join",
        example=",giveaway customize join reaction 🎉",
    )
    @has_permissions(manage_guild=True)
    async def customize_join_reaction(self, ctx: Context, *, emoji: str = None) -> None:
        events = self._events()
        if not events:
            return
        if not emoji or not emoji.strip():
            s = await events.get_settings(ctx.guild.id)
            await ctx.success(
                f"Join reaction is `{s.get('join_reaction') or '🎉'}`"
            )
            return
        await events.update_settings(
            ctx.guild.id,
            join_type="reaction",
            join_reaction=emoji.strip(),
        )
        await ctx.success(
            f"Join type set to **reaction** with emoji {emoji.strip()}"
        )

    @giveaway_customize.command(
        name="button",
        aliases=["btn", "joinbutton"],
        description="Set enter button label and emoji",
        usage="[label] [emoji]",
        example=",giveaway customize button Enter 🎉",
    )
    @has_permissions(manage_guild=True)
    async def customize_button(
        self, ctx: Context, label: str = None, emoji: str = None
    ) -> None:
        events = self._events()
        if not events:
            return
        if label is None and emoji is None:
            s = await events.get_settings(ctx.guild.id)
            await ctx.success(
                f"Button: **{s.get('button_label') or 'Enter'}** "
                f"{s.get('button_emoji') or '🎉'}"
            )
            return
        fields: dict = {}
        if label is not None:
            if label.lower() in {"clear", "reset", "default"}:
                fields["button_label"] = None
            else:
                fields["button_label"] = label[:80]
        if emoji is not None:
            if emoji.lower() in {"clear", "reset", "default"}:
                fields["button_emoji"] = None
            else:
                fields["button_emoji"] = emoji[:100]
        await events.update_settings(ctx.guild.id, **fields)
        s = await events.get_settings(ctx.guild.id)
        await ctx.success(
            f"Button set to **{s.get('button_label') or 'Enter'}** "
            f"{s.get('button_emoji') or '🎉'}"
        )

    @giveaway_customize.command(
        name="showentries",
        aliases=["entries", "showentry", "show"],
        description="Toggle showing entry count on the giveaway panel",
        usage="<on|off>",
        example=",giveaway customize showentries off",
    )
    @has_permissions(manage_guild=True)
    async def customize_showentries(self, ctx: Context, state: str = None) -> None:
        events = self._events()
        if not events:
            return
        if state is None:
            s = await events.get_settings(ctx.guild.id)
            await ctx.success(
                f"Show entries is **{'on' if s.get('show_entries', True) else 'off'}**"
            )
            return
        low = state.lower().strip()
        if low in {"on", "enable", "true", "yes", "1"}:
            await events.update_settings(ctx.guild.id, show_entries=True)
            await ctx.success("Entry count will be **shown**")
            return
        if low in {"off", "disable", "false", "no", "0"}:
            await events.update_settings(ctx.guild.id, show_entries=False)
            await ctx.success("Entry count will be **hidden**")
            return
        await ctx.warn("Use `on` or `off`")

    @giveaway_customize.group(
        name="dmonwin",
        aliases=["dm"],
        invoke_without_command=True,
        description="Toggle DMing winners (default: off)",
        usage="[on|off]",
    )
    @has_permissions(manage_guild=True)
    async def customize_dmonwin(self, ctx: Context, state: str = None) -> None:
        """`,giveaway customize dmonwin on|off` — off by default."""
        events = self._events()
        if events is None:
            await ctx.warn("Giveaway events are not loaded")
            return
        if state is None:
            settings = await events.get_settings(ctx.guild.id)
            on = settings.get("dm_on_win", False)
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
        await ctx.warn("Use `on` or `off`, or `,giveaway customize dmonwin script ...`")

    @customize_dmonwin.command(name="on", description="Enable DMing winners")
    @has_permissions(manage_guild=True)
    async def customize_dmonwin_on(self, ctx: Context) -> None:
        events = self._events()
        if not events:
            return
        await events.set_dm_on_win(ctx.guild.id, True)
        await ctx.success("Winners will be **DM'd** when they win")

    @customize_dmonwin.command(name="off", description="Disable DMing winners")
    @has_permissions(manage_guild=True)
    async def customize_dmonwin_off(self, ctx: Context) -> None:
        events = self._events()
        if not events:
            return
        await events.set_dm_on_win(ctx.guild.id, False)
        await ctx.success("Winners will **not** be DM'd")

    @customize_dmonwin.command(
        name="script",
        aliases=["message", "msg", "template"],
        description="Set a custom DM script for winners",
        usage="[script|clear]",
        example=",giveaway customize dmonwin script {embed}$v{title: You won!}$v{description: **{prize}** in {guild.name}}",
    )
    @has_permissions(manage_guild=True)
    async def customize_dmonwin_script(self, ctx: Context, *, script: str = None) -> None:
        """Customize the winner DM (embed script). Variables work in DMs."""
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

    
    @giveaway.group(
        name="dmonwin",
        aliases=["dmonswin"],
        invoke_without_command=True,
        description="Alias for giveaway customize dmonwin (default off)",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def dmonwin(self, ctx: Context, state: str = None) -> None:
        await self.customize_dmonwin(ctx, state)

    @dmonwin.command(name="on", description="Enable DMing winners")
    @has_permissions(manage_guild=True)
    async def dmonwin_on(self, ctx: Context) -> None:
        await self.customize_dmonwin_on(ctx)

    @dmonwin.command(name="off", description="Disable DMing winners")
    @has_permissions(manage_guild=True)
    async def dmonwin_off(self, ctx: Context) -> None:
        await self.customize_dmonwin_off(ctx)

    @dmonwin.command(
        name="script",
        aliases=["message", "msg", "template"],
        description="Set a custom DM script for winners",
    )
    @has_permissions(manage_guild=True)
    async def dmonwin_script(self, ctx: Context, *, script: str = None) -> None:
        await self.customize_dmonwin_script(ctx, script=script)

async def setup(bot: commands.Bot):
    """Load the Giveaway cog + events."""
    await bot.add_cog(Giveaway(bot))
    await bot.add_cog(GiveawayEvents(bot))
