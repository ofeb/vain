from discord.ext.commands import group
from discord import Embed, TextChannel, Message, Member
from asyncpg import UniqueViolationError
from asyncio import sleep, Lock
from collections import defaultdict
from typing import Optional

from core.discord.package import Package
from core.managers.converters import EmbedConverter
from core.tools.flags.guilds import Parameters
from core.managers.permissions import has_permissions
from core.tools.human.text import humanize_duration


class WelcomeCommands(Package):
    """welcome message setup commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.welcome_locks = defaultdict(Lock)

    @group(
        name="welcome",
        aliases=["welc", "wlc"],
        invoke_without_command=True,
        description="manage messages sent when a member joins the server",
        example=",welcome add #hi Hi {user.mention}! --self_destruct 10",
    )
    @has_permissions(manage_guild=True)
    async def welcome(self, ctx) -> Message:
        """manage welcome messages"""
        return await ctx.send_help()

    @welcome.command(
        name="add",
        aliases=["create", "set"],
        flags=Parameters,
        description="add a welcome message to a channel (defaults to current channel)",
        usage="[channel] <script> [--self_destruct <time>]",
        example=",welcome add #hi Hi {user.mention}! --self_destruct 10",
    )
    @has_permissions(manage_guild=True)
    async def welcome_add(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        """add a welcome channel"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            return await ctx.warn("Text channels only\n> -# **welcome messages can only be sent in text channels**")
        timer = ctx.flags.get("self_destruct")
        if timer is not None and timer < 6:
            return await ctx.warn("Invalid timer\n> -# **self-destruct timer must be at least `6` seconds**")
        try:
            await self.db.execute(
                """INSERT INTO welcome_messages (guild_id, channel_id, message, self_destruct) VALUES ($1, $2, $3, $4);""",
                ctx.guild.id,
                channel.id,
                message.script,
                timer,
            )
        except UniqueViolationError:
            return await ctx.fail(
                f"Welcome message exists\n> -# **remove the existing one first, or use `{ctx.invoke_prefix}welcome edit`**"
            )
        extra = f"\n> -# **the message will delete itself after {humanize_duration(timer)}**" if timer else ""
        return await ctx.success(
            f"Welcome message set for {channel.mention}{extra}"
        )

    @welcome.command(
        name="edit",
        aliases=["change", "update"],
        flags=Parameters,
        description="edit the welcome script for a channel (defaults to current channel)",
        usage="[channel] <script> [--self_destruct <time>]",
        example=",welcome edit #hi Welcome back {user.mention}!",
    )
    @has_permissions(manage_guild=True)
    async def welcome_edit(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        """edit an existing welcome message script"""
        channel = channel or ctx.channel
        timer = ctx.flags.get("self_destruct")
        if timer is not None and timer < 6:
            return await ctx.warn("Invalid timer\n> -# **self-destruct timer must be at least `6` seconds**")
        exists = await self.db.fetchval(
            """SELECT 1 FROM welcome_messages WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )
        if not exists:
            return await ctx.fail(
                f"No welcome message\n> -# **use `{ctx.invoke_prefix}welcome add` to create one first**"
            )
        await self.db.execute(
            """UPDATE welcome_messages SET message = $1, self_destruct = $2
               WHERE guild_id = $3 AND channel_id = $4""",
            message.script,
            timer,
            ctx.guild.id,
            channel.id,
        )
        extra = f"\n> -# **the message will delete itself after {humanize_duration(timer)}**" if timer else ""
        return await ctx.success(f"Updated welcome message for {channel.mention}{extra}")

    @welcome.command(
        name="remove",
        aliases=["delete", "del"],
        description="remove a welcome message from a channel (defaults to current channel)",
        usage="[channel]",
        example=",welcome remove #general",
    )
    @has_permissions(manage_guild=True)
    async def welcome_remove(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        """remove a welcome channel"""
        channel = channel or ctx.channel
        deleted = await self.db.fetchval(
            """DELETE FROM welcome_messages WHERE guild_id = $1 AND channel_id = $2 RETURNING channel_id;""",
            ctx.guild.id,
            channel.id,
        )
        if deleted:
            return await ctx.success(f"Removed welcome message for {channel.mention}")
        return await ctx.fail(f"No welcome message\n> -# **{channel.mention} doesn't have a welcome message set**")

    @welcome.command(
        name="view",
        aliases=["check"],
        description="preview the welcome message for a channel (defaults to current channel)",
        usage="[channel]",
        example=",welcome view #general",
    )
    @has_permissions(manage_guild=True)
    async def welcome_view(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        """preview welcome message"""
        channel = channel or ctx.channel
        msg = await self.db.fetchval(
            """SELECT message FROM welcome_messages WHERE guild_id = $1 AND channel_id = $2;""",
            ctx.guild.id,
            channel.id,
        )
        if not msg:
            return await ctx.fail(f"No welcome message\n> -# **{channel.mention} doesn't have a welcome message set**")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @welcome.command(
        name="list",
        description="list all welcome channels in this server",
        example=",welcome list",
    )
    @has_permissions(manage_guild=True)
    async def welcome_list(self, ctx) -> Message:
        """list all welcome channels"""
        rows = await self.db.fetch(
            """SELECT channel_id FROM welcome_messages WHERE guild_id = $1""",
            ctx.guild.id,
        )
        channels = [
            f"{ch.mention} (`{ch.id}`)"
            for row in rows
            if (ch := ctx.guild.get_channel(row["channel_id"]))
        ]
        if not channels:
            return await ctx.search("no welcome channels set up")
        return await ctx.paginate(Embed(title="Welcome Channels"), channels)

    @welcome.command(
        name="variables",
        aliases=["vars"],
        description="show available template variables for welcome scripts",
        example=",welcome variables",
    )
    @has_permissions(manage_guild=True)
    async def welcome_variables(self, ctx) -> Message:
        """show available template vars"""
        return await ctx.normal(
            "check all **variables** at: https://vain.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    async def on_member_join(self, member: Member) -> None:
        
        try:
            row = await self.db.fetchrow(
                "SELECT raid_active FROM antiraid_config WHERE guild_id = $1",
                member.guild.id,
            )
            if row and row.get("raid_active"):
                return
        except Exception:
            pass

        rate = await self.bot.object_cache.ratelimited(
            f"welcome_messages:{member.guild.id}", 1, 5
        )
        if rate != 0:
            await sleep(5)

        
        
        locks = getattr(self, "join_locks", None)
        if locks is None:
            locks = getattr(self, "welcome_locks", None)
        if locks is None:
            self.welcome_locks = defaultdict(Lock)
            locks = self.welcome_locks

        async with locks[f"welcome_messages:{member.guild.id}"]:
            for row in await self.bot.db.fetch(
                """SELECT * FROM welcome_messages WHERE guild_id = $1;""",
                member.guild.id,
            ):
                ch = member.guild.get_channel(row["channel_id"])
                if not ch:
                    continue
                try:
                    builder = await self.create_embed(
                        row.message, member=member, user=member
                    )
                except Exception:
                    continue
                if row.self_destruct:
                    builder.data["delete_after"] = row.self_destruct
                try:
                    await builder.send(ch)
                except Exception:
                    continue
