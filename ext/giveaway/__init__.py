from __future__ import annotations

import re
from datetime import datetime, timedelta
from random import sample
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color
from core.managers.permissions import has_permissions
from core.tools.moderation_args import (
    is_duration_token,
    parse_duration_seconds,
    format_duration_token,
)


_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CHANNEL_MENTION_RE = re.compile(r"^<#(\d{15,20})>$")
_CHANNEL_ID_RE = re.compile(r"^\d{15,20}$")


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
    """Try to resolve a channel token; return None if it is not a channel."""
    raw = _clean_token(token)
    if not raw or ctx.guild is None:
        return None

    mention = _CHANNEL_MENTION_RE.match(raw)
    channel_id: int | None = int(mention.group(1)) if mention else None
    if channel_id is None and _CHANNEL_ID_RE.match(raw):
        channel_id = int(raw)

    def _usable(ch) -> bool:
        if ch is None:
            return False
        
        if isinstance(ch, (discord.TextChannel, discord.Thread)):
            return True
        return bool(callable(getattr(ch, "send", None)) and getattr(ch, "id", None))

    if channel_id is not None:
        channel = ctx.guild.get_channel(channel_id)
        return channel if _usable(channel) else None

    
    name = raw[1:] if raw.startswith("#") else raw
    if not name or name.startswith("."):
        
        return None

    lowered = name.lower()
    for ch in ctx.guild.text_channels:
        if ch.name.lower() == lowered and _usable(ch):
            return ch
    for ch in list(getattr(ctx.guild, "threads", []) or []):
        if getattr(ch, "name", "").lower() == lowered and _usable(ch):
            return ch
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

    def get_requirements(self, record) -> List[str]:
        r = []
        if record.get("max_level"):
            r.append(f"Must have **level {record['max_level']}**")
        if record.get("min_level"):
            r.append(f"Must have **level {record['min_level']}**")
        if record.get("required_roles"):
            for role_id in record["required_roles"]:
                r.append(f"Must have **<@&{role_id}>**")
        return r

    def _giveaway_embed_lines(
        self,
        end_time,
        winners: int,
        hosts_string: str,
        requirements: List[str] | None = None,
    ) -> List[str]:
        lines = [
            "React with 🎉 to enter the giveaway.",
            f"**Ends:** {discord.utils.format_dt(end_time, style='R')} ({discord.utils.format_dt(end_time, style='F')})",
            f"**Winners:** {winners}",
            f"**Hosted by:** {hosts_string}",
        ]
        if requirements:
            lines.append("**Requirements**")
            lines.extend(requirements)
        return lines

    @group(
        name="giveaway",
        description="Start a giveaway quickly and easily",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def giveaway(self, ctx: Context) -> None:
        """Giveaway management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway.command(
        name="reroll",
        description="Reroll a winner for the specified giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to reroll", winners="Number of winners to pick")
    @has_permissions(manage_channels=True)
    async def reroll(
        self,
        ctx: Context,
        message: discord.Message = None,
        winners: int = 1,
    ) -> None:
        """Reroll a winner for the specified giveaway."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT entries, win_message_id, prize, host FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        
        if not giveaway["win_message_id"]:
            await ctx.warn("That giveaway isn't over yet")
            return
        
        if winners < 1:
            await ctx.warn("Winner count must be higher than 1")
            return
        
        entries = [
            ctx.guild.get_member(i) for i in giveaway["entries"] if ctx.guild.get_member(i)
        ]
        new_winners = sample(entries, winners)
        winners_string = ", ".join(m.mention for m in new_winners)
        embed = panel_embed(
            title=f"Winners for {shorten(giveaway['prize'], 25)}",
            lines=[
                f"{winners_string} {'have' if winners > 1 else 'has'} won the giveaway from <@{giveaway['host']}>",
            ],
            timestamp=False,
        )
        await message.edit(embed=embed)
        await ctx.message.add_reaction("👍")

    @giveaway.command(
        name="end",
        description="End an active giveaway early",
        guild_only=True,
    )
    @describe(message="Giveaway message to end")
    @has_permissions(manage_channels=True)
    async def end(self, ctx: Context, message: discord.Message = None) -> None:
        """End an active giveaway early."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        
        self.bot.dispatch("giveaway_end", ctx.guild, message.channel, giveaway)
        await ctx.message.add_reaction("👍")

    @giveaway.group(
        name="edit",
        description="Edit options and limits for a specific giveaway",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
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
    @has_permissions(manage_channels=True)
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
        end_time = giveaway["expiration"]
        winners = giveaway["winner_count"]
        hosts = []
        for host in giveaway["hosts"]:
            hosts.append(
                self.bot.get_user(host) or await self.bot.fetch_user(host)
            )
        hosts_string = ", ".join(f"{str(m)}" for m in hosts if m is not None)
        requirements = self.get_requirements(giveaway)
        embed = panel_embed(
            title=giveaway["prize"],
            color=color.base,
            lines=self._giveaway_embed_lines(end_time, winners, hosts_string, requirements),
            timestamp=False,
        )
        embed.timestamp = giveaway["created_at"]
        await message.edit(embed=embed)
        await ctx.message.add_reaction("👍")

    @giveaway_edit.command(
        name="prize",
        description="Change prize for a giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", prize="New prize name")
    @has_permissions(manage_channels=True)
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
        
        embed = message.embeds[0]
        embed.title = prize
        await message.edit(embed=embed)
        await self.bot.db.execute(
            "UPDATE giveaways SET prize = $1 WHERE message_id = $2",
            prize,
            message.id,
        )
        await ctx.message.add_reaction("👍")

    @giveaway_edit.command(
        name="duration",
        description="Change the end date for a giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", duration="Duration like 1h, 30m, or seconds")
    @has_permissions(manage_channels=True)
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
        
        end_time = datetime.now() + timedelta(seconds=int(duration))
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
        end_time = giveaway["expiration"]
        winners = giveaway["winner_count"]
        hosts = []
        for host in giveaway["hosts"]:
            hosts.append(
                self.bot.get_user(host) or await self.bot.fetch_user(host)
            )
        hosts_string = ", ".join(f"{str(m)}" for m in hosts if m is not None)
        requirements = self.get_requirements(giveaway)
        embed = panel_embed(
            title=giveaway["prize"],
            color=color.base,
            lines=self._giveaway_embed_lines(end_time, winners, hosts_string, requirements),
            timestamp=False,
        )
        embed.timestamp = giveaway["created_at"]
        await message.edit(embed=embed)
        await ctx.success(f"Set the expiration of the giveaway to {discord.utils.format_dt(end_time, style='R')}")

    @giveaway.command(
        name="start",
        description="Start a new giveaway",
        guild_only=True,
        usage="[channel] <duration> [winners] <prize>",
        example=",giveaway start 2m 1 Nitro Classic",
    )
    @describe(
        arguments="[channel] <duration> [winners] <prize> — e.g. 2m 1 Nitro or #chat 1h 2 Nitro",
    )
    @has_permissions(manage_channels=True)
    async def start(self, ctx: Context, *, arguments: str = None) -> None:
        """Start a new giveaway.

        Syntax: `,giveaway start [channel] <duration> [winners] <prize>`

        Examples:
        - `,giveaway start 1h 1 Nitro Classic`
        - `,giveaway start 2m 1 nitro`
        - `,giveaway start #giveaways 1h 2 Nitro`
        """
        if not arguments or not str(arguments).strip():
            await ctx.warn(
                "Usage: `,giveaway start [channel] <duration> [winners] <prize>` "
                "e.g. `,giveaway start 2m 1 Nitro`"
            )
            return

        try:
            channel, seconds, winners, prize = await _parse_start_args(ctx, arguments)
        except commands.BadArgument as exc:
            await ctx.warn(str(exc))
            return

        end_time = datetime.now() + timedelta(seconds=seconds)

        embed = panel_embed(
            title=prize,
            color=color.base,
            lines=self._giveaway_embed_lines(end_time, winners, ctx.author.mention),
            timestamp=False,
        )
        embed.timestamp = datetime.now()

        message = await channel.send(embed=embed)
        await message.add_reaction("🎉")

        await self.bot.db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, expiration, winner_count, hosts, created_at) VALUES($1, $2, $3, $4, $5, $6, $7, $8)",
            ctx.guild.id,
            channel.id,
            message.id,
            prize,
            end_time,
            winners,
            [ctx.author.id],
            datetime.now(),
        )

        await ctx.success(f"Giveaway started in {channel.mention}")


async def setup(bot: commands.Bot):
    """Load the Giveaway cog + events."""
    from .events import GiveawayEvents

    await bot.add_cog(Giveaway(bot))
    await bot.add_cog(GiveawayEvents(bot))
