from __future__ import annotations

from datetime import datetime
from typing import Optional

import discord
from discord import Member
from discord.ext.commands import group, has_permissions, command

from core.discord.package import Package
from core.discord.views.embed import c2


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

        await ctx.send(
            embed=c2(
                message=(
                    f"> **{target.display_name}'s** birthday\n"
                    f"> -# **date:** {birthday_data}"
                ),
                timestamp=False,
            )
        )

    @birthday.command(
        name="set",
        description="Set your birthday",
    )
    async def birthday_set(self, ctx, *, date: str):
        """set birthday"""
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return await ctx.fail(
                "Please provide a **valid date**\n"
                f"> -# **format:** `YYYY-MM-DD` (e.g. `1995-07-21`)"
            )

        await self.bot.db.execute(
            "INSERT INTO birthday (user_id, guild_id, birthday_date) VALUES($1, $2, $3) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET birthday_date = excluded.birthday_date",
            ctx.author.id, ctx.guild.id, date
        )
        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.author.display_name}'s** birthday set\n"
                    f"> -# **date:** {date}"
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

        my_date = await self.bot.db.fetchval(
            "SELECT birthday_date FROM birthday WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, ctx.guild.id
        )
        their_date = await self.bot.db.fetchval(
            "SELECT birthday_date FROM birthday WHERE user_id = $1 AND guild_id = $2",
            member.id, ctx.guild.id
        )

        if not my_date:
            return await ctx.fail(
                "You haven't set your birthday yet\n"
                f"> -# **set one with:** `,birthday set`"
            )
        if not their_date:
            return await ctx.fail(
                f"{member.mention} hasn't set their birthday\n"
                f"> -# **ask them to use:** `,birthday set`"
            )

        today = datetime.now()
        my_bday = datetime.strptime(my_date, "%Y-%m-%d").replace(year=today.year)
        their_bday = datetime.strptime(their_date, "%Y-%m-%d").replace(year=today.year)

        my_days_until = (my_bday - today).days
        their_days_until = (their_bday - today).days

        if my_days_until < 0:
            my_bday = my_bday.replace(year=today.year + 1)
            my_days_until = (my_bday - today).days
        if their_days_until < 0:
            their_bday = their_bday.replace(year=today.year + 1)
            their_days_until = (their_bday - today).days

        my_str = f"in **{my_days_until}** days" if my_days_until > 0 else "**today**"
        their_str = f"in **{their_days_until}** days" if their_days_until > 0 else "**today**"

        await ctx.send(
            embed=c2(
                message=(
                    f"> **{ctx.author.display_name}** ↔ **{member.display_name}**\n"
                    f"> -# **you:** {my_date} ({my_str})\n"
                    f"> -# **them:** {their_date} ({their_str})"
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
            if member:
                lines.append(f"> {member.mention} — {birthday['birthday_date']}")

        await ctx.send(
            embed=c2(
                message=f"> **all birthdays**\n" + "\n".join(lines),
                timestamp=False,
            )
        )
