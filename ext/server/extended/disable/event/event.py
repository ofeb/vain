from discord.ext.commands import group, has_permissions, CommandError, EventConverter
from discord import Embed, TextChannel
from core.discord.package import Package
from lib.classes.converters import EVENT_MAPPING


class EventDisableCommands(Package):
    """disable bot events per channel"""

    @group(
        name="disableevent",
        description="Disable a bot event in a channel",
        example=",disableevent repost #text",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disableevent(self, ctx, event: EventConverter, *, channel: TextChannel):
        """block an event"""
        row = await self.db.fetchrow(
            """SELECT * FROM disabled_events WHERE guild_id = $1 AND event = $2""",
            ctx.guild.id, event,
        )
        if row:
            ids = list(row.channel_ids)
            ids.append(channel.id)
            await self.db.execute(
                """UPDATE disabled_events SET channel_ids = $1 WHERE guild_id = $2 AND event = $3""",
                ids, ctx.guild.id, event,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_events (guild_id, event, channel_ids) VALUES($1, $2, $3)""",
                ctx.guild.id, event, [channel.id],
            )
        return await ctx.success(
            f"**disabled** `{EVENT_MAPPING[event][0]}` in {channel.mention}"
        )

    @disableevent.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of disabled bot events in guild",
    )
    @has_permissions(manage_channels=True)
    async def disableevent_list(self, ctx):
        """list disabled events"""
        rows = []
        for entry in await self.db.fetch(
            """SELECT event, channel_ids FROM disabled_events WHERE guild_id = $1""",
            ctx.guild.id,
        ):
            label = EVENT_MAPPING[entry.event][0]
            for cid in entry.channel_ids:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    rows.append(f"'{label}' ({ch.mention})")
        if not rows:
            raise CommandError("no events have been disabled")
        numbered = [f"`{i}` {r}" for i, r in enumerate(rows, start=1)]
        return await ctx.paginate(
            Embed(title="Disabled Bot Events", color=self.bot.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @disableevent.command(
        name="all",
        description="Disable a bot event in every channel",
        example=",disableevent all member_join",
    )
    @has_permissions(manage_channels=True)
    async def disableevent_all(self, ctx, event: EventConverter):
        """block event everywhere"""
        await self.db.execute(
            """INSERT INTO disabled_events (guild_id, event, channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, event) DO UPDATE SET channel_ids = excluded.channel_ids""",
            ctx.guild.id,
            event,
            [c.id for c in ctx.guild.channels],
        )
        return await ctx.success(
            f"**disabled** `{EVENT_MAPPING[event][0]}` in all channels"
        )
