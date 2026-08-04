from __future__ import annotations

import discord
from discord.ext.commands import group, CommandError
from discord import TextChannel

from core.discord.package import Package
from core.managers.permissions import has_permissions


class Slowmode(Package):
    """slowmode management"""

    def _parse_delay(self, value: str | int) -> int:
        if isinstance(value, int):
            return max(0, min(int(value), 21600))
        raw = str(value).strip().lower()
        if raw.isdigit():
            return max(0, min(int(raw), 21600))
        units = {"s": 1, "m": 60, "h": 3600}
        if len(raw) >= 2 and raw[-1] in units and raw[:-1].isdigit():
            seconds = int(raw[:-1]) * units[raw[-1]]
            return max(0, min(seconds, 21600))
        raise CommandError("delay must look like `5s`, `10m`, `1h`, or a number of seconds (max 6h)")

    @group(
        name="slowmode",
        aliases=["sm"],
        description="Restricts members to sending one message per interval",
        invoke_without_command=True,
        example=",slowmode 10s",
    )
    @has_permissions(manage_channels=True)
    async def slowmode(
        self,
        ctx,
        delay: str = None,
        channel: TextChannel = None,
    ):
        """set slowmode on a channel (defaults to current channel)"""
        if delay is None:
            return await ctx.send_help(ctx.command)

        # If first arg is a channel mention/name and no second arg, treat as channel lookup fail for delay
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        seconds = self._parse_delay(delay)
        try:
            await channel.edit(slowmode_delay=seconds, reason=f"slowmode by {ctx.author}")
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to set slowmode: {e}")

        if seconds == 0:
            return await ctx.success(f"Disabled slowmode in {channel.mention}")
        return await ctx.success(
            f"Set slowmode in {channel.mention} to **{seconds}** second(s)"
        )

    @slowmode.command(
        name="off",
        aliases=["disable", "0"],
        description="Disables slowmode in a channel",
        example=",slowmode off",
    )
    @has_permissions(manage_channels=True)
    async def slowmode_off(self, ctx, channel: TextChannel = None):
        """disable slowmode (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        try:
            await channel.edit(slowmode_delay=0, reason=f"slowmode off by {ctx.author}")
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
        channel: TextChannel = None,
    ):
        """enable slowmode (defaults to current channel)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        seconds = self._parse_delay(delay)
        if seconds < 1:
            raise CommandError("delay must be at least **1 second** (use `,slowmode off` to disable)")

        try:
            await channel.edit(slowmode_delay=seconds, reason=f"slowmode on by {ctx.author}")
        except discord.Forbidden:
            raise CommandError("I don't have permission to edit this channel")
        except discord.HTTPException as e:
            raise CommandError(f"failed to set slowmode: {e}")

        return await ctx.success(
            f"Set slowmode in {channel.mention} to **{seconds}** second(s)"
        )
