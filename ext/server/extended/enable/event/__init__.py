from __future__ import annotations

import contextlib

from discord.ext.commands import TextChannelConverter, group, CommandError
from discord import Embed, TextChannel
from core.discord.package import Package
from core.managers.converters import EVENT_MAPPING, EventConverter


from core.managers.permissions import has_permissions


class EventEnableCommands(Package):
    """re-enable bot events per channel"""

    async def _parse_channel_event(self, ctx, args: str):
        """Resolve optional channel + required event from free-form tokens."""
        tokens = (args or "").split()
        if not tokens:
            raise CommandError(
                f"Provide an event name\nExample: `{ctx.clean_prefix}enableevent repost`"
            )

        channel: TextChannel | None = None
        event_token: str | None = None

        if len(tokens) == 1:
            event_token = tokens[0]
            channel = ctx.channel if isinstance(ctx.channel, TextChannel) else None
        else:
            with contextlib.suppress(Exception):
                ch = await TextChannelConverter().convert(ctx, tokens[0])
                if isinstance(ch, TextChannel):
                    channel = ch
                    event_token = " ".join(tokens[1:])
            if channel is None:
                with contextlib.suppress(Exception):
                    ch = await TextChannelConverter().convert(ctx, tokens[-1])
                    if isinstance(ch, TextChannel):
                        channel = ch
                        event_token = " ".join(tokens[:-1])
            if channel is None:
                channel = ctx.channel if isinstance(ctx.channel, TextChannel) else None
                event_token = " ".join(tokens)

        if channel is None:
            raise CommandError("Provide a **text channel** (or run this in one)")
        if not event_token:
            raise CommandError(
                f"Provide an event name\nExample: `{ctx.clean_prefix}enableevent repost`"
            )

        event = await EventConverter().convert(ctx, event_token)
        return channel, event

    @group(
        name="enableevent",
        aliases=["ee"],
        description="enable a bot event in a channel (defaults to current channel)",
        example=",enableevent repost  or  ,enableevent #text repost",
        usage="[channel] <event>",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def enableevent(self, ctx, *, args: str = ""):
        """enable event in channel"""
        channel, event = await self._parse_channel_event(ctx, args)
        stored = await self.db.fetchval(
            """SELECT channel_ids FROM disabled_events WHERE guild_id = $1 AND event = $2""",
            ctx.guild.id,
            event,
        )
        if not stored:
            raise CommandError("that event wasn't disabled anywhere")
        if channel.id not in stored:
            raise CommandError(f"that event wasn't disabled in {channel.mention}")
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
        description="enables a bot event in every channel",
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
        description="view a list of enabled bot events in guild",
    )
    @has_permissions(manage_channels=True)
    async def enableevent_list(self, ctx):
        """list enabled events"""
        all_events = list(EVENT_MAPPING.keys())
        for entry in await self.db.fetch(
            """SELECT event, channel_ids FROM disabled_events WHERE guild_id = $1""",
            ctx.guild.id,
        ):
            if entry.event in all_events:
                all_events.remove(entry.event)
        if not all_events:
            return await ctx.warn("all events are disabled")
        numbered = [f"`{i}` `{EVENT_MAPPING[e][0]}`" for i, e in enumerate(all_events, start=1)]
        return await ctx.paginate(
            Embed(title="Enabled Bot Events", color=self.bot.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )
