from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import Embed, TextChannel
from discord.ext.commands import group, CommandError
from humanize import naturaldelta

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.managers.converters import EmbedConverter

if TYPE_CHECKING:
    from core.vain import Vain


class Nuke(Package):
    """nuke management"""

    @group(
        name="nuke",
        description="Clone the current channel",
        invoke_without_command=True,
    )
    @has_permissions(administrator=True)
    async def nuke(self, ctx):
        channel_info = [ctx.channel.category, ctx.channel.position]
        channel_id = ctx.channel.id
        await ctx.channel.clone(reason=f"Nuked by {str(ctx.author)}")
        await ctx.channel.delete(reason=f"Nuked by {str(ctx.author)}")
        new_channel = channel_info[0].text_channels[-1]
        await new_channel.edit(position=channel_info[1])
        asyncio.ensure_future(self.update_channels(ctx.channel, new_channel))
        await new_channel.send(content="first")

    async def update_channels(self, old: TextChannel, new: TextChannel) -> None:
        old_id = old.id
        new_id = new.id
        guild_id = old.guild.id

        
        
        tables = [
            ("guilds", "welcome_channel_id", False),
            ("guilds", "leave_channel_id", False),
            ("guilds", "boost_channel_id", False),
            ("server_settings", "jail_channel_id", False),
            ("server_settings", "jail_message_channel_id", False),
            ("server_settings", "joinlog_channel_id", False),
            ("log_config", "channel_id", False),
            ("log_config", "ignored_channels", True),
            ("modlog_config", "channel_id", False),
            ("moderation_config", "log_channel", False),
            ("roleplay_config", "action_channel", False),
            ("information_config", "info_channel", False),
            ("join_messages", "channel_id", False),
            ("leave_messages", "channel_id", False),
            ("boost_messages", "channel_id", False),
            ("suggest_settings", "channel_id", False),
            ("suggest_settings", "review_channel_id", False),
            ("birthday_notifications", "channel_id", False),
            ("bump_reminder", "channel_id", False),
            ("counters", "channel_id", False),
            ("clownboard", "channel_id", False),
            ("starboard", "channel_id", False),
            ("button_roles", "channel_id", False),
            ("giveaways", "channel_id", False),
            ("ticket_settings", "log_channel_id", False),
            ("ticket_settings", "transcript_channel_id", False),
            ("ticket_panels", "channel_id", False),
            ("tictactoe_channel", "channel_id", False),
            ("disabled_events", "channel_ids", True),
            ("disabled_modules", "channel_ids", True),
            ("auto_responders", "allowed_channel_ids", True),
            ("auto_responders", "denied_channel_ids", True),
            ("trackers", "channel_ids", True),
            ("invite_config", "channel_id", False),
        ]

        for table, column, is_array in tables:
            if is_array:
                await self.db.execute(
                    f"UPDATE {table} SET {column} = array_replace({column}, $1, $2) WHERE guild_id = $3 AND $1 = ANY({column})",
                    old_id,
                    new_id,
                    guild_id,
                )
            else:
                await self.db.execute(
                    f"UPDATE {table} SET {column} = $2 WHERE guild_id = $3 AND {column} = $1",
                    old_id,
                    new_id,
                    guild_id,
                )

    @nuke.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View all scheduled nukes",
    )
    @has_permissions(administrator=True)
    async def nuke_list(self, ctx):
        if not (
            rows := await self.db.fetch(
                """SELECT channel_id, nuke_threshold FROM nuke WHERE guild_id = $1""",
                ctx.guild.id,
            )
        ):
            raise CommandError("No scheduled nuking channels found")

        embed = Embed(title="Scheduled Nukes", color=self.color)
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        values = []
        i = 0
        for row in rows:
            if channel := ctx.guild.get_channel(row["channel_id"]):
                i += 1
                values.append(
                    f"`{i}` {channel.mention} - {naturaldelta(row['nuke_threshold'])}"
                )
        return await ctx.paginate(embed, values)

    @nuke.command(
        name="remove",
        aliases=["delete", "del", "rem", "r", "d"],
        description="Remove scheduled nuke for a channel",
        example=",nuke remove #text",
    )
    @has_permissions(administrator=True)
    async def nuke_remove(self, ctx, *, channel: TextChannel):
        if not (
            data := await self.db.fetchrow(
                """DELETE FROM nuke WHERE guild_id = $1 AND channel_id = $2 RETURNING *""",
                ctx.guild.id,
                channel.id,
            )
        ):
            raise CommandError("No scheduled nuke found for this channel")
        return await ctx.success(
            f"Removed {channel.mention} from the **scheduled nukes**"
        )

    @nuke.command(
        name="add",
        aliases=["create", "cr", "c", "a"],
        description="Schedule nuke for a channel (yes. this will reclone the channel)",
        example=",nuke add #general 2h hey sexy ass people",
    )
    @has_permissions(administrator=True)
    async def nuke_add(
        self,
        ctx,
        channel: TextChannel,
        interval: int,
        *,
        message: Optional[str] = "first",
    ):
        await self.db.execute(
            """INSERT INTO nuke (guild_id, channel_id, last_nuke, nuke_threshold, message) VALUES($1, $2, $3, $4, $5) ON CONFLICT(guild_id, channel_id) DO UPDATE SET last_nuke = excluded.last_nuke, nuke_threshold = excluded.nuke_threshold, message = excluded.message""",
            ctx.guild.id,
            channel.id,
            datetime.now(),
            int(interval),
            message,
        )
        return await ctx.success(
            f"Added {channel.mention} as a **scheduled nuke** to be nuked every **{naturaldelta(interval)}**\nwith message: `{message}`"
        )
