from discord.ext.commands import group, CommandError
from discord import Embed, TextChannel
from core.discord.package import Package
from lib.classes.converters import EVENT_MAPPING


from core.managers.converters import EventConverter
from core.managers.permissions import has_permissions
class EventEnableCommands(Package):
    """re-enable bot events per channel"""

    @group(
        name="enableevent",
        aliases=["ee"],
        description="Enable a bot event in a channel",
        example=",enableevent repost #text",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def enableevent(self, ctx, channel: TextChannel, event: EventConverter):
        """enable event in channel"""
        stored = await self.db.fetchval(
            """SELECT channel_ids FROM disabled_events WHERE guild_id = $1 AND event = $2""",
            ctx.guild.id,
            event,
        )
        if not stored:
            raise CommandError("that event wasnt disabled anywhere")
        if channel.id not in stored:
            raise CommandError(f"that event wasnt disabled in {channel.mention}")
        stored.remove(channel.id)
        await self.db.execute(
            """UPDATE disabled_events SET channel_ids = $1 WHERE guild_id = $2 AND event = $3""",
            stored, ctx.guild.id, event,
        )
        return await ctx.success(
            f"**enabled** `{EVENT_MAPPING[event][0]}` in {channel.mention}"
        )

    @enableevent.command(
        name="all",
        description="Enables a bot event in every channel",
        example=",enableevent all repost",
    )
    @has_permissions(manage_channels=True)
    async def enableevent_all(self, ctx, event: EventConverter):
        """enable event everywhere"""
        await self.db.execute(
            """DELETE FROM disabled_events WHERE guild_id = $1 AND event = $2""",
            ctx.guild.id,
            event,
        )
        return await ctx.success(
            f"**enabled** `{EVENT_MAPPING[event][0]}` in all channels"
        )

    @enableevent.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of enabled bot events in guild",
    )
    @has_permissions(manage_channels=True)
    async def enableevent_list(self, ctx):
        """list enabled events"""
        rows = []
        all_events = list(EVENT_MAPPING.keys())
        for entry in await self.db.fetch(
            """SELECT event, channel_ids FROM disabled_events WHERE guild_id = $1""",
            ctx.guild.id,
        ):
            if entry.event in all_events:
                all_events.remove(entry.event)
        if not all_events:
            return await ctx.fail("all events are disabled")
        numbered = [f"`{i}` `{EVENT_MAPPING[e][0]}`" for i, e in enumerate(all_events, start=1)]
        return await ctx.paginate(
            Embed(title="Enabled Bot Events", color=self.bot.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )
