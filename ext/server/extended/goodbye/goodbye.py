from discord.ext.commands import group
from discord import Embed, TextChannel, Message, Member
from asyncpg import UniqueViolationError
from asyncio import sleep, Lock
from collections import defaultdict
from core.discord.package import Package
from lib.classes.flags.servers import Parameters


from core.managers.permissions import has_permissions
class GoodbyeCommands(Package):
    """goodbye message setup commands"""

    def __init__(self, bot):
        """init with locks"""
        super().__init__(bot)
        self.leave_locks = defaultdict(Lock)

    @group(
        name="goodbye",
        usage="(subcommand) <args> --params",
        example="goodbye add #bye See ya {user}",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def goodbye(self, ctx) -> Message:
        """manage goodbye messages"""
        return await ctx.send_help()

    @goodbye.command(
        name="add",
        usage="(channel) (message) --params",
        example="#goodbye See ya! {user}",
        aliases=["create"],
        flags=Parameters,
    )
    @has_permissions(manage_guild=True)
    async def goodbye_add(
        self, ctx, channel: TextChannel, *, message
    ) -> Message:
        """add a goodbye channel"""
        timer = ctx.flags.get("self_destruct")
        if timer:
            if timer < 6:
                return await ctx.warn("self-destruct timer must be at least `6` seconds")
            if timer > 60:
                return await ctx.warn("self-destruct timer must stay under `60` seconds")
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
                f"already a goodbye message in {channel.mention}, remove it first"
            )
        extra = f"\nmessages will delete after `{timer}` seconds" if timer else ""
        return await ctx.success(
            f"goodbye message set for {channel.mention}{extra}"
        )

    @goodbye.command(
        name="remove",
        example=",goodbye remove #general",
        aliases=["delete", "del"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_remove(self, ctx, *, channel: TextChannel) -> Message:
        """remove a goodbye channel"""
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
        example=",goodbye view #general",
        aliases=["check"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_view(self, ctx, *, channel: TextChannel) -> Message:
        """preview goodbye message"""
        msg = await self.db.fetchval(
            """SELECT message FROM leave_messages WHERE guild_id = $1 AND channel_id = $2;""",
            ctx.guild.id,
            channel.id,
        )
        if not msg:
            return await ctx.fail(f"no goodbye message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @goodbye.command(name="list")
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

    @goodbye.command(name="variables", aliases=["vars"])
    @has_permissions(manage_guild=True)
    async def goodbye_variables(self, ctx) -> Message:
        """show available template vars"""
        return await ctx.normal(
            "check all **variables** at: https://bleed.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    async def on_member_remove(self, member: Member) -> None:
        """fire on member leave"""
        if await self.db.get_antiraid_state(member.guild.id):
            return

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
                builder = await self.create_embed(
                    row.message, member=member, user=member
                )
                if row.self_destruct:
                    builder.data["delete_after"] = row.self_destruct
                try:
                    await builder.send(ch)
                except Exception:
                    continue
