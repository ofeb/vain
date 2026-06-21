from __future__ import annotations

from asyncio import Lock, sleep
from collections import defaultdict

from asyncpg import UniqueViolationError
from discord import Embed, Member, Message, TextChannel
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.converters import EmbedConverter
from lib.classes.flags.servers import Parameters


from core.managers.permissions import has_permissions
class BoostCommands(Package):
    """boost message setup commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.boost_locks = defaultdict(Lock)

    @group(
        name="boosts",
        usage="(subcommand) <args> --params",
        example="boosts add #general thanks {user.mention}!",
        aliases=["boost"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def boosts(self, ctx) -> Message:
        """manage boost messages"""
        return await ctx.send_help()

    @boosts.command(
        name="add",
        usage="(channel) (message) --params",
        example="#general thanks {user.mention}!",
        aliases=["create"],
        flags=Parameters,
    )
    @has_permissions(manage_guild=True)
    async def boosts_add(self, ctx, channel: TextChannel, *, message: EmbedConverter) -> Message:
        """add a boost channel"""
        timer = ctx.flags.get("self_destruct")
        if timer:
            if timer < 6:
                return await ctx.warn("self-destruct timer must be at least `6` seconds")
            if timer > 60:
                return await ctx.warn("self-destruct timer must stay under `60` seconds")

        try:
            await self.db.execute(
                """INSERT INTO boost_messages (guild_id, channel_id, message, self_destruct) VALUES ($1, $2, $3, $4);""",
                ctx.guild.id,
                channel.id,
                message.script,
                timer,
            )
        except UniqueViolationError:
            return await ctx.fail(
                f"there's already a boost message for {channel.mention}, remove it first"
            )

        extra = f"\nmessages will delete after `{timer}` seconds" if timer else ""
        return await ctx.success(f"boost message set for {channel.mention}{extra}")

    @boosts.command(
        name="remove",
        usage="(channel)",
        example=",boosts remove #general",
        aliases=["delete", "del"],
    )
    @has_permissions(manage_guild=True)
    async def boosts_remove(self, ctx, *, channel: TextChannel) -> Message:
        """remove a boost channel"""
        deleted = await self.db.fetchval(
            """DELETE FROM boost_messages WHERE guild_id = $1 AND channel_id = $2 RETURNING channel_id;""",
            ctx.guild.id,
            channel.id,
        )
        if deleted:
            return await ctx.success(f"removed boost message for {channel.mention}")
        return await ctx.fail(f"no boost message set for {channel.mention}")

    @boosts.command(
        name="view",
        usage="(channel)",
        example=",boosts view #general",
        aliases=["check"],
    )
    @has_permissions(manage_guild=True)
    async def boosts_view(self, ctx, *, channel: TextChannel) -> Message:
        """preview boost message"""
        msg = await self.db.fetchval(
            """SELECT message FROM boost_messages WHERE guild_id = $1 AND channel_id = $2;""",
            ctx.guild.id,
            channel.id,
        )
        if not msg:
            return await ctx.fail(f"no boost message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @boosts.command(name="list")
    @has_permissions(manage_guild=True)
    async def boosts_list(self, ctx) -> Message:
        """list all boost channels"""
        rows = await self.db.fetch(
            """SELECT channel_id FROM boost_messages WHERE guild_id = $1""",
            ctx.guild.id,
        )
        channels = [
            f"{ch.mention} (`{ch.id}`)"
            for row in rows
            if (ch := ctx.guild.get_channel(row["channel_id"]))
        ]
        if not channels:
            return await ctx.search("no boost channels set up")
        return await ctx.paginate(Embed(title="Boost Channels"), channels)

    @boosts.command(name="variables", aliases=["vars"])
    @has_permissions(manage_guild=True)
    async def boosts_variables(self, ctx) -> Message:
        """show available template vars"""
        return await ctx.normal(
            "check all **variables** at: https://bleed.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    async def on_member_boost(self, member: Member) -> None:
        """send boost messages when a member starts boosting"""
        rate = await self.bot.object_cache.ratelimited(
            f"boost_messages:{member.guild.id}", 1, 5
        )
        if rate != 0:
            await sleep(5)

        async with self.boost_locks[f"boost_messages:{member.guild.id}"]:
            for row in await self.bot.db.fetch(
                """SELECT * FROM boost_messages WHERE guild_id = $1;""",
                member.guild.id,
            ):
                channel = member.guild.get_channel(row["channel_id"])
                if not channel:
                    continue

                try:
                    builder = await self.create_embed(
                        row.message,
                        member=member,
                        user=member,
                    )
                except Exception:
                    continue
                if row.self_destruct:
                    builder.data["delete_after"] = row.self_destruct

                try:
                    await builder.send(channel)
                except Exception:
                    continue
