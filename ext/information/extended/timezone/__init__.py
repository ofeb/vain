from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytz
from discord import Member
from discord.ext.commands import group, has_permissions, command

from core.discord.package import Package
from core.discord.views.embed import c2


def _time_period(hour: int) -> str:
    if 0 <= hour < 6:
        return "early morning"
    elif 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


class Timezone(Package):
    """timezone management"""

    def __init__(self, bot):
        self.bot = bot

    @group(
        name="timezone",
        aliases=["tz"],
        description="View your current time or somebody elses",
        invoke_without_command=True,
    )
    async def timezone(self, ctx, member: Optional[Member] = None):
        """view timezone"""
        target = member or ctx.author
        tz = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            target.id, ctx.guild.id
        )

        if not tz:
            return await ctx.warn(
                f"{target.mention} has not set their timezone"
            )

        try:
            user_tz = pytz.timezone(tz)
            current_time = datetime.now(user_tz)
            hour = current_time.hour
            period = _time_period(hour)
            time_str = current_time.strftime("%I:%M").lstrip("0")
            day_str = current_time.strftime("%A").lower()
            await ctx.send(
                embed=c2(
                    message=(
                        f"**{target.display_name}'s** time is "
                        f"**{time_str}** **{day_str}** **{period}**"
                    ),
                    timestamp=False,
                )
            )
        except pytz.exceptions.UnknownTimeZoneError:
            return await ctx.fail(
                f"Invalid timezone stored for {target.mention}\n"
                f"> -# **zone:** `{tz}` · ask them to reset with `,timezone set`"
            )

    @timezone.command(
        name="set",
        description="Set your timezone",
    )
    async def timezone_set(self, ctx, *, location: str):
        """set timezone"""
        try:
            pytz.timezone(location)
        except pytz.exceptions.UnknownTimeZoneError:
            return await ctx.fail(
                "Please provide a **valid timezone**\n"
                f"> -# **example:** `Europe/Dublin` or a country like `Ireland`"
            )

        await self.bot.db.execute(
            "INSERT INTO users (user_id, guild_id, timezone) VALUES($1, $2, $3) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET timezone = excluded.timezone",
            ctx.author.id, ctx.guild.id, location
        )
        await ctx.success(
                    f"> **{ctx.author.display_name}'s** timezone set\n"
                    f"> -# **zone:** {location}"
                )

    @timezone.command(
        name="remove",
        aliases=["delete", "del", "reset", "clear"],
        description="Remove your timezone",
    )
    async def timezone_remove(self, ctx):
        """remove timezone"""
        result = await self.bot.db.execute(
            "UPDATE users SET timezone = NULL WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, ctx.guild.id
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                "You have no timezone set\n"
                f"> -# **set one with:** `,timezone set`"
            )
        await ctx.send(
            embed=c2(
                message=f"> **{ctx.author.display_name}'s** timezone removed",
                timestamp=False,
            )
        )

    @timezone.command(
        name="compare",
        description="Compare your time with another member",
    )
    async def timezone_compare(self, ctx, member: Member):
        """compare timezones"""
        if member.id == ctx.author.id:
            return await ctx.warn(
                "You cannot compare with yourself\n"
                f"> -# **usage:** `,timezone compare @user`"
            )

        my_tz_name = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, ctx.guild.id
        )
        their_tz_name = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            member.id, ctx.guild.id
        )

        if not my_tz_name:
            return await ctx.fail(
                "You haven't set your timezone yet\n"
                f"> -# **set one with:** `,timezone set`"
            )
        if not their_tz_name:
            return await ctx.fail(
                f"{member.mention} hasn't set their timezone\n"
                f"> -# **ask them to use:** `,timezone set`"
            )

        try:
            my_tz = pytz.timezone(my_tz_name)
            their_tz = pytz.timezone(their_tz_name)
        except pytz.exceptions.UnknownTimeZoneError:
            return await ctx.fail(
                "One of the stored timezones is invalid\n"
                f"> -# **re-set with:** `,timezone set`"
            )

        my_time = datetime.now(my_tz)
        their_time = datetime.now(their_tz)

        my_period = _time_period(my_time.hour)
        their_period = _time_period(their_time.hour)
        my_str = my_time.strftime("%I:%M").lstrip("0")
        their_str = their_time.strftime("%I:%M").lstrip("0")

        diff_hours = (their_time.utcoffset().total_seconds() - my_time.utcoffset().total_seconds()) / 3600
        if diff_hours == 0:
            diff_str = "same timezone"
        elif diff_hours > 0:
            diff_str = f"+{diff_hours:.1f}h ahead"
        else:
            diff_str = f"{diff_hours:.1f}h behind"

        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.author.display_name}** ↔ **{member.display_name}**\n"
                    f"> -# **you:** {my_str} {my_period} ({my_tz_name})\n"
                    f"> -# **them:** {their_str} {their_period} ({their_tz_name})\n"
                    f"> -# **difference:** {diff_str}"
                ),
                timestamp=False,
            )
        )

    @timezone.command(
        name="list",
        description="View a list of every member's timezone",
    )
    async def timezone_list(self, ctx):
        """list all timezones"""
        timezones = await self.bot.db.fetch(
            "SELECT user_id, timezone FROM users WHERE guild_id = $1 AND timezone IS NOT NULL",
            ctx.guild.id
        )

        if not timezones:
            return await ctx.warn(
                "No timezones set in this server\n"
                f"> -# **set yours with:** `,timezone set`"
            )

        lines = []
        for tz in timezones:
            member = ctx.guild.get_member(tz['user_id'])
            if member:
                try:
                    user_tz = pytz.timezone(tz['timezone'])
                    current_time = datetime.now(user_tz)
                    period = _time_period(current_time.hour)
                    time_str = current_time.strftime("%I:%M").lstrip("0")
                    lines.append(
                        f"> {member.mention} — {time_str} {period} ({tz['timezone']})"
                    )
                except pytz.exceptions.UnknownTimeZoneError:
                    lines.append(f"> {member.mention} — invalid ({tz['timezone']})")

        await ctx.send(
            embed=c2(
                message=f"> **all timezones**\n" + "\n".join(lines),
                timestamp=False,
            )
        )
