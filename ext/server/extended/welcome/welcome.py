from discord.ext.commands import group
from discord import Embed, TextChannel, Message, Member, AllowedMentions
from asyncpg import UniqueViolationError
from asyncio import sleep, Lock
from collections import defaultdict
from core.discord.package import Package
from core.managers.converters import EmbedConverter
from lib.classes.flags.servers import Parameters


from core.managers.permissions import has_permissions
class WelcomeCommands(Package):
    """welcome message setup commands"""

    def __init__(self, bot):
        """init with locks"""
        super().__init__(bot)
        self.join_locks = defaultdict(Lock)

    @group(
        name="welcome",
        example=",welcome add #hi Hi {user.mention}! --self_destruct 10",
        aliases=["welc"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def welcome(self, ctx) -> Message:
        """manage welcome messages"""
        return await ctx.send_help()

    @welcome.command(
        name="add",
        example=",welcome add #hi Hi {user.mention}! --self_destruct 10",
        aliases=["create", "set"],
        flags=Parameters,
    )
    @has_permissions(manage_guild=True)
    async def welcome_add(
        self, ctx, channel: TextChannel, *, message: EmbedConverter
    ) -> Message:
        """add a welcome channel"""
        timer = ctx.flags.get("self_destruct")
        if timer:
            if timer < 6:
                return await ctx.warn("self-destruct timer must be at least `6` seconds")
            if timer > 60:
                return await ctx.warn("self-destruct timer must stay under `60` seconds")
        try:
            await self.db.execute(
                """INSERT INTO join_messages (guild_id, channel_id, message, self_destruct) VALUES ($1, $2, $3, $4);""",
                ctx.guild.id,
                channel.id,
                message.script,
                timer,
            )
        except UniqueViolationError:
            return await ctx.fail(
                f"there's already a welcome message for {channel.mention}, remove it first"
            )
        extra = f"\nmessages will delete after `{timer}` seconds" if timer else ""
        return await ctx.success(
            f"welcome message set for {channel.mention}{extra}"
        )

    @welcome.command(
        name="remove",
        example=",welcome remove #general",
        aliases=["delete", "del"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_remove(self, ctx, *, channel: TextChannel) -> Message:
        """remove a welcome channel"""
        deleted = await self.db.fetchval(
            """DELETE FROM join_messages WHERE guild_id = $1 AND channel_id = $2 RETURNING channel_id;""",
            ctx.guild.id,
            channel.id,
        )
        if deleted:
            return await ctx.success(f"removed welcome message for {channel.mention}")
        return await ctx.fail(f"no welcome message set for {channel.mention}")

    @welcome.command(
        name="view",
        example=",welcome view #general",
        aliases=["check"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_view(self, ctx, *, channel: TextChannel) -> Message:
        """preview welcome message"""
        msg = await self.db.fetchval(
            """SELECT message FROM join_messages WHERE guild_id = $1 AND channel_id = $2;""",
            ctx.guild.id,
            channel.id,
        )
        if not msg:
            return await ctx.fail(f"no welcome message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @welcome.command(name="list")
    @has_permissions(manage_guild=True)
    async def welcome_list(self, ctx) -> Message:
        """list all welcome channels"""
        rows = await self.db.fetch(
            """SELECT channel_id FROM join_messages WHERE guild_id = $1""",
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

    @welcome.command(name="variables", aliases=["vars"])
    @has_permissions(manage_guild=True)
    async def welcome_variables(self, ctx) -> Message:
        """show available template vars"""
        return await ctx.normal(
            "check all **variables** at: https://bleed.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    async def _ping_on_join(self, member: Member):
        """ping member on join"""
        ids = await self.bot.db.fetchval(
            """SELECT channel_ids FROM pingonjoin WHERE guild_id = $1""",
            member.guild.id,
        )
        if not ids:
            return
        for cid in ids:
            ch = member.guild.get_channel(cid)
            if not ch:
                continue
            await ch.send(
                f"{member.mention}", allowed_mentions=AllowedMentions(users=True)
            )

    async def on_member_agree(self, member: Member) -> None:
        """send welcome on join"""
        if await self.db.get_antiraid_state(member.guild.id):
            return

        rate = await self.bot.object_cache.ratelimited(
            f"welcome_messages:{member.guild.id}", 1, 5
        )
        if rate != 0:
            await sleep(5)
        async with self.join_locks[f"welcome_messages:{member.guild.id}"]:
            await self._ping_on_join(member)
            for row in await self.bot.db.fetch(
                """SELECT * FROM join_messages WHERE guild_id = $1;""",
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
