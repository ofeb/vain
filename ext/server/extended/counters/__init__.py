from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

import discord
from discord import ChannelType
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from config import color
from core.managers.permissions import has_permissions

from core.discord.views.embed import panel_embed

from .settings import Settings as CountersSettings

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
        description="create counters for everybody to see",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def counter(self, ctx: Context) -> None:
        """Counter management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @counter.command(
        name="add",
        description="create channel counter",
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
        settings = await CountersSettings.fetch(self.bot, ctx.guild)
        existing = next((r for r in settings.rows if r["counter_type"] == option), None)
        if existing:
            if not ctx.guild.get_channel(existing["channel_id"]):
                await settings.remove_where(counter_type=option)
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
        
        await settings.add(channel_id=channel.id, counter_type=option)
        await ctx.success(f"{channel.mention} will now keep track of the {option} count")

    @counter.command(
        name="remove",
        description="remove a channel or category counter",
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
        settings = await CountersSettings.fetch(self.bot, ctx.guild)
        if not any(r["channel_id"] == channel.id for r in settings.rows):
            await ctx.warn(f"There is no counter in {channel.mention}")
            return
        
        if action == RemovalActionType.delete:
            await channel.delete(reason=f"counter deleted by {ctx.author}")
            msg = f"Successfully DELETED {channel.mention}"
        else:
            msg = f"Successfully REMOVED the counter for {channel.mention}"
        
        await settings.remove_where(channel_id=channel.id)
        await ctx.success(msg)

    @counter.command(
        name="list",
        description="list every category or channel keeping track of members or boosters in this server",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def counter_list(self, ctx: Context) -> None:
        """List every category or channel keeping track of members or boosters."""
        settings = await CountersSettings.fetch(self.bot, ctx.guild)
        if not settings.rows:
            await ctx.warn("No category or channel are keeping track of members or boosts")
            return
        
        rows = []
        for i, counter in enumerate(settings.rows, start=1):
            rows.append(f"`{i}` <#{counter['channel_id']}> - **{counter['counter_type']}**")
        embed = panel_embed(title="Counters", color=color.base, lines=rows, timestamp=False)
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Counters(bot))
