from discord.ext.commands import group, has_permissions, CommandError
from discord import Embed, TextChannel
from asyncio import Lock
from collections import defaultdict
from core.discord.package import Package


class StickymessageCommands(Package):
    """sticky message commands"""

    def __init__(self, bot):
        """init with state"""
        super().__init__(bot)
        self.sticky_locks = defaultdict(Lock)
        self.pinned_ids = {}

    @group(
        name="stickymessage",
        aliases=["sticky", "sm"],
        description="Set up a sticky message in one or multiple channels",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage(self, ctx):
        """sticky message help"""
        return await ctx.send_help(ctx.command)

    @stickymessage.command(
        name="view",
        description="View the sticky message for a channel",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_view(self, ctx, *, channel: TextChannel):
        """preview a sticky"""
        code = await self.db.fetchval(
            """SELECT code FROM sticky_message WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )
        if not code:
            raise CommandError(f"no sticky message in {channel.mention}")
        return await ctx.bot.send_embed(ctx.channel, code, user=ctx.author)

    @stickymessage.command(
        name="add",
        description="Add a sticky message to a channel",
        example=",stickymessage add #general hello everyone",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_add(self, ctx, channel: TextChannel, *, message: str):
        """set a sticky"""
        await self.db.execute(
            """INSERT INTO sticky_message (guild_id, channel_id, code) VALUES($1, $2, $3) ON CONFLICT(guild_id, channel_id) DO UPDATE SET code = excluded.code""",
            ctx.guild.id,
            channel.id,
            message,
        )
        return await ctx.success(f"sticky message set in {channel.mention}")

    @stickymessage.command(name="list", description="View all sticky messages")
    @has_permissions(manage_guild=True)
    async def stickymessage_list(self, ctx):
        """list all stickies"""
        entries = await self.db.fetch(
            """SELECT channel_id, code FROM sticky_message WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not entries:
            raise CommandError("no sticky messages exist")
        lines = [
            f"`{i}` {ctx.guild.get_channel(e.channel_id)}"
            for i, e in enumerate(entries, start=1)
        ]
        return await ctx.paginate(
            Embed(title="Sticky Messages", color=self.bot.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            lines,
        )

    @stickymessage.command(
        name="remove",
        aliases=["delete", "del"],
        description="Remove a sticky message from a channel",
        example=",stickymessage remove #general",
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_remove(self, ctx, *, channel: TextChannel):
        """remove a sticky"""
        await self.db.execute(
            """DELETE FROM sticky_message WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )
        return await ctx.success(f"sticky removed from {channel.mention}")

    async def on_valid_message(self, ctx):
        """repost sticky on new message"""
        async with self.sticky_locks[f"sticky_message:{ctx.channel.id}"]:
            cfg = await self.bot.db.fetchrow(
                """SELECT code, last_message FROM sticky_message WHERE guild_id = $1 AND channel_id = $2""",
                ctx.guild.id,
                ctx.channel.id,
            )
            if not cfg:
                return
            prev_id = self.pinned_ids.get(ctx.channel.id) or cfg.last_message
            if prev_id:
                try:
                    await self.bot.http.delete_message(ctx.channel.id, prev_id)
                except Exception:
                    pass
            new_msg = await self.bot.send_embed(
                ctx.channel, cfg.code, user=ctx.author
            )
            await self.bot.db.execute(
                """UPDATE sticky_message SET last_message = $1 WHERE guild_id = $2 AND channel_id = $3""",
                new_msg.id,
                ctx.guild.id,
                ctx.channel.id,
            )
            self.pinned_ids[new_msg.channel.id] = new_msg.id
