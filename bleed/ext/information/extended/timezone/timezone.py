from __future__ import annotations

from discord.ext.commands import group
from datetime import datetime, timezone
import pytz

from core.discord.package import Package


class Timezone(Package):
    """timezone management"""

    def __init__(self, bot):
        self.bot = bot

    @group(
        name="timezone",
        description="View your current time or somebody elses",
        invoke_without_command=True,
    )
    async def timezone(self, ctx, member=None):
        """view timezone"""
        target = member or ctx.author
        tz = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            target.id, ctx.guild.id
        )
        
        if not tz:
            return await ctx.send(f"{target.mention} has not set their timezone")
        
        try:
            user_tz = pytz.timezone(tz)
            current_time = datetime.now(user_tz)
            await ctx.send(f"{target.mention}'s time: {current_time.strftime('%Y-%m-%d %H:%M:%S')} ({tz})")
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(f"Invalid timezone: {tz}")

    @timezone.command(
        name="set",
        description="Set your timezone",
    )
    async def timezone_set(self, ctx, location: str):
        """set timezone"""
        try:
            pytz.timezone(location)
        except pytz.exceptions.UnknownTimeZoneError:
            return await ctx.send("Invalid timezone. Use IANA timezone format (e.g., 'America/New_York')")
        
        await self.bot.db.execute(
            "INSERT INTO users (user_id, guild_id, timezone) VALUES($1, $2, $3) ON CONFLICT(user_id, guild_id) DO UPDATE SET timezone = excluded.timezone",
            ctx.author.id, ctx.guild.id, location
        )
        await ctx.success(f"Timezone set to {location}")

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
            return await ctx.send("No timezones set in this server")
        
        rows = []
        for tz in timezones:
            member = ctx.guild.get_member(tz['user_id'])
            if member:
                rows.append(f"{member.mention}: {tz['timezone']}")
        
        await ctx.send("\n".join(rows))
