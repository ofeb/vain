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


class GoodbyeCommands(Package):
    """goodbye message setup commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.leave_locks = defaultdict(Lock)

    @group(
        name="goodbye",
        aliases=["bye", "gb", "leave"],
        invoke_without_command=True,
        description="Manage messages sent when a member leaves the server",
        example=",goodbye add #bye See ya {user}!",
    )
    @has_permissions(manage_guild=True)
    async def goodbye(self, ctx) -> Message:
        """manage goodbye messages"""
        return await ctx.send_help()

    @goodbye.command(
        name="add",
        aliases=["create", "set"],
        flags=Parameters,
        description="Add a goodbye message to a channel (defaults to current channel)",
        usage="[channel] <script> [--self_destruct <time>]",
        example=",goodbye add #bye See ya {user}!",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_add(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        """add a goodbye channel"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only set goodbye messages in text channels")
        timer = ctx.flags.get("self_destruct")
        if timer is not None and timer < 6:
            return await ctx.warn("self-destruct timer must be at least `6` seconds")
        try:
            await self.db.execute(
                """INSERT INTO leave_messages (guild_id, channel_id, message, self_destruct) VALUES ($1, $2, $3, $4);""",
                ctx.guild.id,
                channel.id,
                message.script,
                timer,
            )
        except UniqueViolationError:
            return await ctx.fail(
                f"there's already a goodbye message in {channel.mention} - remove it first or use `{ctx.clean_prefix}goodbye edit`"
            )
        extra = f"\n> -# **the message will delete itself after {humanize_duration(timer)}**" if timer else ""
        return await ctx.success(
            f"goodbye message set for {channel.mention}{extra}"
        )

    @goodbye.command(
        name="edit",
        aliases=["change", "update"],
        flags=Parameters,
        description="Edit the goodbye script for a channel (defaults to current channel)",
        usage="[channel] <script> [--self_destruct <time>]",
        example=",goodbye edit #bye Farewell {user}!",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_edit(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        """edit an existing goodbye message script"""
        channel = channel or ctx.channel
        timer = ctx.flags.get("self_destruct")
        if timer is not None and timer < 6:
            return await ctx.warn("self-destruct timer must be at least `6` seconds")
        exists = await self.db.fetchval(
            """SELECT 1 FROM leave_messages WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )
        if not exists:
            return await ctx.fail(
                f"no goodbye message for {channel.mention} - use `{ctx.clean_prefix}goodbye add` first"
            )
        await self.db.execute(
            """UPDATE leave_messages SET message = $1, self_destruct = $2
               WHERE guild_id = $3 AND channel_id = $4""",
            message.script,
            timer,
            ctx.guild.id,
            channel.id,
        )
        extra = f"\n> -# **the message will delete itself after {humanize_duration(timer)}**" if timer else ""
        return await ctx.success(f"updated goodbye message for {channel.mention}{extra}")

    @goodbye.command(
        name="remove",
        aliases=["delete", "del"],
        description="Remove a goodbye message from a channel (defaults to current channel)",
        usage="[channel]",
        example=",goodbye remove #general",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_remove(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        """remove a goodbye channel"""
        channel = channel or ctx.channel
        deleted = await self.db.fetchval(
            """DELETE FROM leave_messages WHERE guild_id = $1 AND channel_id = $2 RETURNING channel_id;""",
            ctx.guild.id,
            channel.id,
        )
        if deleted:
            return await ctx.success(f"removed goodbye message for {channel.mention}")
        return await ctx.fail(f"no goodbye message set for {channel.mention}")

    @goodbye.command(
        name="view",
        aliases=["check"],
        description="Preview the goodbye message for a channel (defaults to current channel)",
        usage="[channel]",
        example=",goodbye view #general",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_view(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        """preview goodbye message"""
        channel = channel or ctx.channel
        msg = await self.db.fetchval(
            """SELECT message FROM leave_messages WHERE guild_id = $1 AND channel_id = $2;""",
            ctx.guild.id,
            channel.id,
        )
        if not msg:
            return await ctx.fail(f"no goodbye message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @goodbye.command(
        name="list",
        description="List all goodbye channels in this server",
        example=",goodbye list",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_list(self, ctx) -> Message:
        """list all goodbye channels"""
        rows = await self.db.fetch(
            """SELECT channel_id FROM leave_messages WHERE guild_id = $1""",
            ctx.guild.id,
        )
        channels = [
            f"{ch.mention} (`{ch.id}`)"
            for row in rows
            if (ch := ctx.guild.get_channel(row["channel_id"]))
        ]
        if not channels:
            return await ctx.search("no goodbye channels set up")
        return await ctx.paginate(Embed(title="Goodbye Channels"), channels)

    @goodbye.command(
        name="variables",
        aliases=["vars"],
        description="Show available template variables for goodbye scripts",
        example=",goodbye variables",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_variables(self, ctx) -> Message:
        """show available template vars"""
        return await ctx.normal(
            "check all **variables** at: https://vain.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    async def on_member_remove(self, member: Member) -> None:
        # Safe antiraid gate (get_antiraid_state does not exist on db)
        try:
            row = await self.db.fetchrow(
                "SELECT raid_active FROM antiraid_config WHERE guild_id = $1",
                member.guild.id,
            )
            if row and row.get("raid_active"):
                return
        except Exception:
            pass

        invite_info = {}
        try:
            invites_data = await self.bot.db.fetchrow(
                """SELECT * FROM invite_tracker WHERE guild_id = $1 AND user_id = $2""",
                member.guild.id,
                member.id,
            )
            if invites_data:
                inviter = member.guild.get_member(invites_data["inviter_id"]) or await self.bot.fetch_user(
                    invites_data["inviter_id"]
                )
                if inviter:
                    invite_info = {
                        "inviter": inviter,
                        "invite": {
                            "code": invites_data["code"],
                        }
                    }
        except Exception:
            pass

        rate = await self.bot.object_cache.ratelimited(
            f"leave_messages:{member.guild.id}", 1, 5
        )
        if rate != 0:
            await sleep(5)
        async with self.leave_locks[f"leave_messages:{member.guild.id}"]:
            for row in await self.bot.db.fetch(
                """SELECT * FROM leave_messages WHERE guild_id = $1;""",
                member.guild.id,
            ):
                ch = member.guild.get_channel(row["channel_id"])
                if not ch:
                    continue
                try:
                    builder = await self.create_embed(
                        row.message, member=member, user=member, **invite_info
                    )
                except Exception:
                    continue
                if row.self_destruct:
                    builder.data["delete_after"] = row.self_destruct
                try:
                    await builder.send(ch)
                except Exception:
                    continue
