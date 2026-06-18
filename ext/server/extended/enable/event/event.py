from discord.ext.commands import group, has_permissions, CommandError, EventConverter
from discord import TextChannel
from core.discord.package import Package
from lib.classes.converters import EVENT_MAPPING


class EventEnableCommands(Package):
    """re-enable bot events per channel"""

    @group(
        name="enableevent",
        description="Enable a bot event in a channel",
        example=",enableevent repost #text",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def enableevent(self, ctx, event: EventConverter, channel: TextChannel):
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
