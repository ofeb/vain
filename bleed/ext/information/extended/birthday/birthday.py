from __future__ import annotations

from discord.ext.commands import group
from datetime import datetime

from core.discord.package import Package
from core.managers.values import color


class Birthday(Package):
    """birthday management"""

    def __init__(self, bot):
        self.bot = bot
        self.color = color.base

    @group(
        name="birthday",
        description="View your birthday or somebody elses",
        invoke_without_command=True,
    )
    async def birthday(self, ctx, member=None):
        """view birthday"""
        target = member or ctx.author
        birthday_data = await self.bot.db.fetchval(
            "SELECT birthday_date FROM birthday WHERE user_id = $1 AND guild_id = $2",
            target.id, ctx.guild.id
        )
        
        if not birthday_data:
            return await ctx.send(f"{target.mention} has not set their birthday")
        
        await ctx.send(f"{target.mention}'s birthday is {birthday_data}")

    @birthday.command(
        name="unlock",
        description="No description given",
    )
    async def birthday_unlock(self, ctx):
        """unlock birthday feature"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            ctx.guild.id, ctx.channel.id, "Happy birthday {user}!", None
        )
        await ctx.success("Birthday feature unlocked")

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
            return await ctx.send("No birthdays set in this server")
        
        rows = []
        for birthday in birthdays:
            member = ctx.guild.get_member(birthday['user_id'])
            if member:
                rows.append(f"{member.mention}: {birthday['birthday_date']}")
        
        await ctx.send("\n".join(rows))

    @birthday.command(
        name="channel",
        description="No description given",
    )
    async def birthday_channel(self, ctx, channel):
        """set birthday channel"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            ctx.guild.id, channel.id, "Happy birthday {user}!", None
        )
        await ctx.success(f"Birthday channel set to {channel.mention}")

    @birthday.command(
        name="role",
        description="No description given",
    )
    async def birthday_role(self, ctx, role):
        """set birthday role"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET role_id = excluded.role_id",
            ctx.guild.id, ctx.channel.id, "Happy birthday {user}!", role.id
        )
        await ctx.success(f"Birthday role set to {role.mention}")

    @birthday.command(
        name="lock",
        description="No description given",
    )
    async def birthday_lock(self, ctx):
        """lock birthday feature"""
        await self.bot.db.execute(
            "DELETE FROM birthday_notifications WHERE guild_id = $1",
            ctx.guild.id
        )
        await ctx.success("Birthday feature locked")

    @birthday.command(
        name="config",
        description="No description given",
    )
    async def birthday_config(self, ctx):
        """configure birthday feature"""
        config = await self.bot.db.fetchrow(
            "SELECT channel_id, message, role_id FROM birthday_notifications WHERE guild_id = $1",
            ctx.guild.id
        )
        
        if not config:
            return await ctx.send("Birthday feature not configured")
        
        channel = ctx.guild.get_channel(config['channel_id'])
        role = ctx.guild.get_role(config['role_id']) if config['role_id'] else None
        
        await ctx.send(f"Channel: {channel.mention if channel else 'Not set'}\nMessage: {config['message']}\nRole: {role.mention if role else 'Not set'}")

    @birthday.command(
        name="set",
        description="No description given",
    )
    async def birthday_set(self, ctx, date: str):
        """set birthday"""
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return await ctx.send("Invalid date format. Use YYYY-MM-DD")
        
        await self.bot.db.execute(
            "INSERT INTO birthday (user_id, guild_id, birthday_date) VALUES($1, $2, $3) ON CONFLICT(user_id, guild_id) DO UPDATE SET birthday_date = excluded.birthday_date",
            ctx.author.id, ctx.guild.id, date
        )
        await ctx.success(f"Birthday set to {date}")

    @birthday.command(
        name="celebrate",
        description="No description given",
    )
    async def birthday_celebrate(self, ctx, role):
        """celebrate birthday"""
        await self.bot.db.execute(
            "INSERT INTO birthday_notifications (guild_id, channel_id, message, role_id) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET role_id = excluded.role_id",
            ctx.guild.id, ctx.channel.id, "Happy birthday {user}!", role.id
        )
        await ctx.success(f"Birthday celebration role set to {role.mention}")

    @birthday.command(
        name="celebrate list",
        description="No description given",
    )
    async def birthday_celebrate_list(self, ctx):
        """list birthday celebrations"""
        config = await self.bot.db.fetchrow(
            "SELECT channel_id, message, role_id FROM birthday_notifications WHERE guild_id = $1",
            ctx.guild.id
        )
        
        if not config:
            return await ctx.send("Birthday celebration not configured")
        
        channel = ctx.guild.get_channel(config['channel_id'])
        role = ctx.guild.get_role(config['role_id']) if config['role_id'] else None
        
        await ctx.send(f"Channel: {channel.mention if channel else 'Not set'}\nMessage: {config['message']}\nRole: {role.mention if role else 'Not set'}")
