from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import discord
from dateutil import relativedelta as rl
from dateutil.parser import parse as parse_date
from discord import Member
from discord.ext.commands import group, has_permissions, command

from core.discord.package import Package
from core.discord.views.embed import c2


MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def _coerce_date(value) -> date | None:
    """Coerce a DB value (date, datetime, or str) into a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return parse_date(value, dayfirst=True).date()
        except (ValueError, OverflowError):
            return None
    return None


def _parse_birthday(raw: str) -> date | None:
    """Parse any humanly readable birthday string into a date."""
    s = raw.strip()
    if not s:
        return None
    try:
        parsed = parse_date(s, dayfirst=True)
    except (ValueError, OverflowError):
        return None
    return parsed.date()


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _format_date(bday: date) -> str:
    return f"{MONTHS[bday.month - 1]} {_ordinal(bday.day)}"


def _until_birthday(bday: date, today: date) -> tuple[int, int] | None:
    """Return (months, days) until the next occurrence, or None if it's today."""
    this_year = bday.replace(year=today.year)
    if (this_year.month, this_year.day) == (today.month, today.day):
        return None
    if this_year < today:
        next_bday = bday.replace(year=today.year + 1)
    else:
        next_bday = this_year
    rd = rl.relativedelta(next_bday, today)
    return rd.months, rd.days


def _until_str(months: int, days: int) -> str:
    parts = []
    if months:
        parts.append(f"**{months}** month{'s' if months != 1 else ''}")
    if days:
        parts.append(f"**{days}** day{'s' if days != 1 else ''}")
    if not parts:
        return ""
    return " and ".join(parts)


class Birthday(Package):
    """birthday management"""

    @group(
        name="birthday",
        aliases=["bday"],
        description="View your birthday or somebody elses",
        invoke_without_command=True,
    )
    async def birthday(self, ctx, member: Optional[Member] = None):
        """view birthday"""
        target = member or ctx.author
        birthday_data = await self.bot.db.fetchval(
            "SELECT birthday_date FROM birthday WHERE user_id = $1 AND guild_id = $2",
            target.id, ctx.guild.id
        )

        if not birthday_data:
            return await ctx.warn(
                f"{target.mention} has not set their birthday"
            )

        bday = _coerce_date(birthday_data)
        if not bday:
            return await ctx.warn(
                f"{target.mention}'s stored birthday is invalid"
            )

        name = target.display_name
        until = _until_birthday(bday, date.today())
        if until is None:
            message = f"> **{name}'s** birthday is **today**!"
        else:
            months, days = until
            message = (
                f"> **{name}'s** birthday is on **{_format_date(bday)}**, "
                f"that's in {_until_str(months, days)}"
            )

        await ctx.send(embed=c2(message=message, timestamp=False))

    @birthday.command(
        name="set",
        description="Set your birthday",
    )
    async def birthday_set(self, ctx, *, date: str):
        """set birthday"""
        parsed = _parse_birthday(date)
        if not parsed:
            return await ctx.fail(
                "Please provide a **valid date**\n"
                f"> -# **examples:** `31/01/10`, `31-01-10`, `31st Jan`, `Jan 31`"
            )

        await self.bot.db.execute(
            "INSERT INTO birthday (user_id, guild_id, birthday_date) VALUES($1, $2, $3) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET birthday_date = excluded.birthday_date",
            ctx.author.id, ctx.guild.id, parsed
        )
        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.author.display_name}'s** birthday set\n"
                    f"> -# **date:** {_format_date(parsed)}"
                ),
                timestamp=False,
            )
        )

    @birthday.command(
        name="remove",
        aliases=["delete", "del", "reset", "clear"],
        description="Remove your birthday",
    )
    async def birthday_remove(self, ctx):
        """remove birthday"""
        result = await self.bot.db.execute(
            "DELETE FROM birthday WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, ctx.guild.id
        )
        if result == "DELETE 0":
            return await ctx.warn(
                "You have no birthday set\n"
                f"> -# **set one with:** `,birthday set`"
            )
        await ctx.send(
            embed=c2(
                message=f"> **{ctx.author.display_name}'s** birthday removed",
                timestamp=False,
            )
        )

    @birthday.command(
        name="compare",
        description="Compare your birthday with another member",
    )
    async def birthday_compare(self, ctx, member: Member):
        """compare birthdays"""
        if member.id == ctx.author.id:
            return await ctx.warn(
                "You cannot compare with yourself\n"
                f"> -# **usage:** `,birthday compare @user`"
            )

        my_raw = await self.bot.db.fetchval(
            "SELECT birthday_date FROM birthday WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, ctx.guild.id
        )
        their_raw = await self.bot.db.fetchval(
            "SELECT birthday_date FROM birthday WHERE user_id = $1 AND guild_id = $2",
            member.id, ctx.guild.id
        )

        if not my_raw:
            return await ctx.fail(
                "You haven't set your birthday yet\n"
                f"> -# **set one with:** `,birthday set`"
            )
        if not their_raw:
            return await ctx.fail(
                f"{member.mention} hasn't set their birthday\n"
                f"> -# **ask them to use:** `,birthday set`"
            )

        my_date = _coerce_date(my_raw)
        their_date = _coerce_date(their_raw)
        if not my_date or not their_date:
            return await ctx.fail(
                "One of the stored birthdays is invalid\n"
                f"> -# **re-set with:** `,birthday set`"
            )

        today = date.today()
        my_until = _until_birthday(my_date, today)
        their_until = _until_birthday(their_date, today)

        my_str = _until_str(*my_until) if my_until else "**today**"
        their_str = _until_str(*their_until) if their_until else "**today**"

        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.author.display_name}** ↔ **{member.display_name}**\n"
                    f"> -# **you:** {_format_date(my_date)} ({my_str})\n"
                    f"> -# **them:** {_format_date(their_date)} ({their_str})"
                ),
                timestamp=False,
            )
        )

    @birthday.command(
        name="unlock",
        description="Unlock birthday feature for this server",
    )
    @has_permissions(manage_guild=True)
    async def birthday_unlock(self, ctx):
        """unlock birthday feature"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) "
            "VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            ctx.guild.id, ctx.channel.id, "Happy birthday {user}!", None
        )
        await ctx.send(
            embed=c2(
                message=f"> **{ctx.guild.name}** birthday feature unlocked",
                timestamp=False,
            )
        )

    @birthday.command(
        name="lock",
        description="Lock birthday feature for this server",
    )
    @has_permissions(manage_guild=True)
    async def birthday_lock(self, ctx):
        """lock birthday feature"""
        await self.bot.db.execute(
            "DELETE FROM birthday_notifications WHERE guild_id = $1",
            ctx.guild.id
        )
        await ctx.send(
            embed=c2(
                message=f"> **{ctx.guild.name}** birthday feature locked",
                timestamp=False,
            )
        )

    @birthday.command(
        name="channel",
        description="Set the birthday announcement channel",
    )
    @has_permissions(manage_guild=True)
    async def birthday_channel(self, ctx, channel: discord.TextChannel):
        """set birthday channel"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) "
            "VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            ctx.guild.id, channel.id, "Happy birthday {user}!", None
        )
        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.guild.name}** birthday channel set\n"
                    f"> -# **channel:** {channel.mention}"
                ),
                timestamp=False,
            )
        )

    @birthday.command(
        name="role",
        description="Set the birthday role",
    )
    @has_permissions(manage_guild=True)
    async def birthday_role(self, ctx, role: discord.Role):
        """set birthday role"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) "
            "VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET role_id = excluded.role_id",
            ctx.guild.id, ctx.channel.id, "Happy birthday {user}!", role.id
        )
        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.guild.name}** birthday role set\n"
                    f"> -# **role:** {role.mention}"
                ),
                timestamp=False,
            )
        )

    @birthday.command(
        name="config",
        description="View birthday configuration",
    )
    async def birthday_config(self, ctx):
        """view birthday config"""
        config = await self.bot.db.fetchrow(
            "SELECT channel_id, message, role_id FROM birthday_notifications WHERE guild_id = $1",
            ctx.guild.id
        )

        if not config:
            return await ctx.warn(
                "Birthday feature not configured\n"
                f"> -# **unlock with:** `,birthday unlock`"
            )

        channel = ctx.guild.get_channel(config['channel_id'])
        role = ctx.guild.get_role(config['role_id']) if config['role_id'] else None

        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.guild.name}** birthday config\n"
                    f"> -# **channel:** {channel.mention if channel else 'not set'}\n"
                    f"> -# **role:** {role.mention if role else 'not set'}\n"
                    f"> -# **message:** {config['message']}"
                ),
                timestamp=False,
            )
        )

    @birthday.command(
        name="list",
        description="View a list of every member's birthday",
    )
    async def birthday_list(self, ctx):
        """list all birthdays"""
        birthdays = await self.bot.db.fetch(
            "SELECT user_id, birthday_date FROM birthday WHERE guild_id = $1 ORDER BY birthday_date",
            ctx.guild.id
        )

        if not birthdays:
            return await ctx.warn(
                "No birthdays set in this server\n"
                f"> -# **add yours with:** `,birthday set`"
            )

        lines = []
        for birthday in birthdays:
            member = ctx.guild.get_member(birthday['user_id'])
            bday = _coerce_date(birthday['birthday_date'])
            if member and bday:
                lines.append(f"> {member.mention} — {_format_date(bday)}")

        await ctx.send(
            embed=c2(
                message=f"> **all birthdays**\n" + "\n".join(lines),
                timestamp=False,
            )
        )
