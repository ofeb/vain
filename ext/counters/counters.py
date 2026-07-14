from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

import discord
from discord import ChannelType
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color
from core.tools.aesthetic import panel_embed
from core.managers.permissions import has_permissions

if TYPE_CHECKING:
    from .events import CountersEvents


CHANNEL_OPTIONS = {
    ChannelType.stage_voice: ["stage", "s", "st"],
    ChannelType.voice: ["voice", "v", "vc"],
    ChannelType.text: ["text", "t", "txt"],
    ChannelType.category: ["category", "c", "cat"],
    ChannelType.news: ["news", "n"],
    ChannelType.forum: ["forum", "f", "frm"],
    ChannelType.media: ["media", "img", "imgs", "m", "md", "i"],
}

COUNTER_OPTIONS = {
    "members": ["members", "member", "mems", "m"],
    "boosters": ["boosters", "boosted", "bstrs"],
    "boosts": ["boosts", "bsts", "bst"],
}


class RemovalActionType(Enum):
    delete = auto()
    remove = auto()


class ChannelTypeConverter(commands.Converter):
    async def convert(self, ctx: Context, argument: str):
        for key, values in CHANNEL_OPTIONS.items():
            for value in values:
                if argument.lower() == value.lower():
                    return key
        raise commands.CommandError(f"{argument} was not a proper channel type")


class CounterOption(commands.Converter):
    async def convert(self, ctx: Context, argument: str):
        for key, values in COUNTER_OPTIONS.items():
            for value in values:
                if argument.lower() == value.lower():
                    return key
        raise commands.CommandError(f"{argument} was not a proper counter type")


class RemovalAction(commands.Converter):
    async def convert(self, ctx: Context, argument: str) -> RemovalActionType:
        delete = ["del", "d", "delete"]
        rem = ["remove", "r", "rem"]
        if argument.lower() in delete:
            return RemovalActionType.delete
        elif argument.lower() in rem:
            return RemovalActionType.remove
        raise commands.CommandError(f"{argument} was not a proper removal action")


class Counters(commands.Cog):
    """Channel counter management system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @group(
        name="counter",
        description="Create counters for everybody to see",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def counter(self, ctx: Context) -> None:
        """Counter management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @counter.command(
        name="add",
        description="Create channel counter",
        guild_only=True,
    )
    @describe(option="Counter type", channel_type="Channel type")
    @has_permissions(manage_channels=True)
    async def counter_add(
        self,
        ctx: Context,
        option: CounterOption,
        channel_type: ChannelTypeConverter,
    ) -> None:
        """Create channel counter."""
        existing = await self.bot.db.fetchrow(
            "SELECT * FROM counters WHERE guild_id = $1 AND counter_type = $2",
            ctx.guild.id,
            option,
        )
        if existing:
            if not ctx.guild.get_channel(existing["channel_id"]):
                await self.bot.db.execute(
                    "DELETE FROM counters WHERE guild_id = $1 AND counter_type = $2",
                    ctx.guild.id,
                    option,
                )
            else:
                await ctx.warn(f"You already have a {option} counter")
                return
        
        if option == "members":
            num = len(ctx.guild.members)
        elif option == "boosters":
            num = len(ctx.guild.premium_subscribers)
        else:
            num = ctx.guild.premium_subscription_count
        
        try:
            channel = await ctx.guild.create_channel(
                name=f"{num} {option}",
                channel_type=channel_type,
            )
        except Exception:
            raise commands.CommandError(
                f"Your guild doesn't have access to {channel_type} type of channels"
            )
        
        await self.bot.db.execute(
            "INSERT INTO counters (guild_id, channel_id, counter_type) VALUES($1, $2, $3)",
            ctx.guild.id,
            channel.id,
            option,
        )
        await ctx.success(f"{channel.mention} will now keep track of the {option} count")

    @counter.command(
        name="remove",
        description="Remove a channel or category counter",
        guild_only=True,
    )
    @describe(channel="Channel to remove counter from", action="Action to perform")
    @has_permissions(manage_channels=True)
    async def counter_remove(
        self,
        ctx: Context,
        channel: discord.abc.GuildChannel,
        action: RemovalAction = RemovalActionType.remove,
    ) -> None:
        """Remove a channel or category counter."""
        if not await self.bot.db.fetchrow(
            "SELECT * FROM counters WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        ):
            await ctx.warn(f"There is no counter in {channel.mention}")
            return
        
        if action == RemovalActionType.delete:
            await channel.delete(reason=f"counter deleted by {ctx.author}")
            msg = f"Successfully DELETED {channel.mention}"
        else:
            msg = f"Successfully REMOVED the counter for {channel.mention}"
        
        await self.bot.db.execute(
            "DELETE FROM counters WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        await ctx.success(msg)

    @counter.command(
        name="list",
        description="List every category or channel keeping track of members or boosters in this server",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def counter_list(self, ctx: Context) -> None:
        """List every category or channel keeping track of members or boosters."""
        counters = await self.bot.db.fetch(
            "SELECT * FROM counters WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not counters:
            await ctx.warn("No category or channel are keeping track of members or boosts")
            return
        
        rows = []
        for i, counter in enumerate(counters, start=1):
            rows.append(f"`{i}` <#{counter['channel_id']}> - **{counter['counter_type']}**")
        embed = panel_embed(title="Counters", color=color.base, lines=rows, timestamp=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Counters(bot))
