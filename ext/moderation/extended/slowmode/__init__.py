from __future__ import annotations

import discord
from discord.ext.commands import group, CommandError
from discord import TextChannel

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.tools.human.text import humanize_duration
from core.tools.moderation_args import parse_duration_seconds


class Slowmode(Package):
    """slowmode management"""

    def _parse_delay(self, value: str | int) -> int:
        if isinstance(value, int):
            return max(0, min(int(value), 21600))
        raw = str(value).strip().lower()
        if raw.isdigit():
            return max(0, min(int(raw), 21600))
        seconds = parse_duration_seconds(raw)
        if seconds is not None:
            return max(0, min(seconds, 21600))
        units = {"s": 1, "m": 60, "h": 3600}
        if len(raw) >= 2 and raw[-1] in units and raw[:-1].isdigit():
            return max(0, min(int(raw[:-1]) * units[raw[-1]], 21600))
        raise CommandError(
            "delay must look like `5s`, `10m`, `1h`, or a number of seconds (max 6h)"
        )

    @group(
        name="slowmode",
        aliases=["sm", "slowmo", "slow", "cooldown"],
        description="Restricts members to sending one message per interval",
        invoke_without_command=True,
        example=",slowmode 10s #general",
        usage="slowmode 10s #general",
    )
    @has_permissions(manage_channels=True)
    async def slowmode(
        self,
        ctx,
        time: str | None = None,
        channel: TextChannel | None = None,
    ):
        """Enable slowmode option in a text channel"""
        if time is None:
            return await ctx.send_help(ctx.command)

        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        seconds = self._parse_delay(time)
        max_duration = 6 * 60 * 60
        if seconds > max_duration:
            return await ctx.warn("You can't set a slowmode for more than **6 hours**")

        try:
            await channel.edit(
                slowmode_delay=seconds,
                reason=f"Slowmode invoked by {ctx.author}",
            )
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to set slowmode: {e}")

        if seconds == 0:
            return await ctx.success(f"Disabled slowmode in {channel.mention}")

        formatted = humanize_duration(seconds)
        return await ctx.success(
            f"Slowmode for {channel.mention} set to **{formatted}**"
        )

    @slowmode.command(
        name="off",
        aliases=["disable", "0", "remove", "delete", "del", "rm", "reset"],
        description="Disables slowmode in a channel",
        example=",slowmode off",
    )
    @has_permissions(manage_channels=True)
    async def slowmode_off(self, ctx, channel: TextChannel | None = None):
        """disable slowmode (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        try:
            await channel.edit(
                slowmode_delay=0,
                reason=f"Slowmode invoked by {ctx.author}",
            )
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to disable slowmode: {e}")

        return await ctx.success(f"Disabled slowmode in {channel.mention}")

    @slowmode.command(
        name="on",
        aliases=["enable", "set"],
        description="Enable slowmode in a channel",
        example=",slowmode on 10s",
    )
    @has_permissions(manage_channels=True)
    async def slowmode_on(
        self,
        ctx,
        delay: str,
        channel: TextChannel | None = None,
    ):
        """enable slowmode (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        seconds = self._parse_delay(delay)
        if seconds < 1:
            raise CommandError(
                "delay must be at least **1 second** (use `,slowmode off` to disable)"
            )
        if seconds > 6 * 60 * 60:
            return await ctx.warn("You can't set a slowmode for more than **6 hours**")

        try:
            await channel.edit(
                slowmode_delay=seconds,
                reason=f"Slowmode invoked by {ctx.author}",
            )
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to set slowmode: {e}")

        formatted = humanize_duration(seconds)
        return await ctx.success(
            f"Slowmode for {channel.mention} set to **{formatted}**"
        )
