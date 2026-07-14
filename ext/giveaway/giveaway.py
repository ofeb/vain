from __future__ import annotations

from datetime import datetime, timedelta
from random import sample
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color
from core.tools.aesthetic import panel_embed
from core.managers.permissions import has_permissions

if TYPE_CHECKING:
    from typing import List


def shorten(text: str, length: int):
    return text[:length] + "..." if len(text) > length else text


class Giveaway(commands.Cog):
    """Giveaway management system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_requirements(self, record) -> List[str]:
        r = []
        if record.get("max_level"):
            r.append(f"Must have **level {record['max_level']}**")
        if record.get("min_level"):
            r.append(f"Must have **level {record['min_level']}**")
        if record.get("required_roles"):
            for role_id in record["required_roles"]:
                r.append(f"Must have **<@&{role_id}>**")
        return r

    def _giveaway_embed_lines(
        self,
        end_time,
        winners: int,
        hosts_string: str,
        requirements: List[str] | None = None,
    ) -> List[str]:
        lines = [
            "React with 🎉 to enter the giveaway.",
            f"**Ends:** {discord.utils.format_dt(end_time, style='R')} ({discord.utils.format_dt(end_time, style='F')})",
            f"**Winners:** {winners}",
            f"**Hosted by:** {hosts_string}",
        ]
        if requirements:
            lines.append("**Requirements**")
            lines.extend(requirements)
        return lines

    @group(
        name="giveaway",
        description="Start a giveaway quickly and easily",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def giveaway(self, ctx: Context) -> None:
        """Giveaway management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway.command(
        name="reroll",
        description="Reroll a winner for the specified giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to reroll", winners="Number of winners to pick")
    @has_permissions(manage_channels=True)
    async def reroll(
        self,
        ctx: Context,
        message: discord.Message = None,
        winners: int = 1,
    ) -> None:
        """Reroll a winner for the specified giveaway."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT entries, win_message_id, prize, host FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        
        if not giveaway["win_message_id"]:
            await ctx.warn("That giveaway isn't over yet")
            return
        
        if winners < 1:
            await ctx.warn("Winner count must be higher than 1")
            return
        
        entries = [
            ctx.guild.get_member(i) for i in giveaway["entries"] if ctx.guild.get_member(i)
        ]
        new_winners = sample(entries, winners)
        winners_string = ", ".join(m.mention for m in new_winners)
        embed = panel_embed(
            title=f"Winners for {shorten(giveaway['prize'], 25)}",
            lines=[
                f"{winners_string} {'have' if winners > 1 else 'has'} won the giveaway from <@{giveaway['host']}>",
            ],
            timestamp=False,
        )
        await message.edit(embed=embed)
        await ctx.message.add_reaction("👍")

    @giveaway.command(
        name="end",
        description="End an active giveaway early",
        guild_only=True,
    )
    @describe(message="Giveaway message to end")
    @has_permissions(manage_channels=True)
    async def end(self, ctx: Context, message: discord.Message = None) -> None:
        """End an active giveaway early."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        
        self.bot.dispatch("giveaway_end", ctx.guild, message.channel, giveaway)
        await ctx.message.add_reaction("👍")

    @giveaway.group(
        name="edit",
        description="Edit options and limits for a specific giveaway",
        guild_only=True,
    )
    @has_permissions(manage_channels=True)
    async def giveaway_edit(self, ctx: Context) -> None:
        """Giveaway edit management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway_edit.command(
        name="maxlevel",
        description="Set the maximum level requirement for giveaway entry",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", level="Maximum level required")
    @has_permissions(manage_channels=True)
    async def giveaway_edit_maxlevel(
        self,
        ctx: Context,
        message: discord.Message = None,
        level: int = 1,
    ) -> None:
        """Set the maximum level requirement for giveaway entry."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        try:
            await self.bot.db.execute(
                "UPDATE giveaways SET max_level = $1 WHERE message_id = $2",
                level,
                message.id,
            )
        except Exception:
            await ctx.warn("That is not a giveaway")
            return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        end_time = giveaway["expiration"]
        winners = giveaway["winner_count"]
        hosts = []
        for host in giveaway["hosts"]:
            hosts.append(
                self.bot.get_user(host) or await self.bot.fetch_user(host)
            )
        hosts_string = ", ".join(f"{str(m)}" for m in hosts if m is not None)
        requirements = self.get_requirements(giveaway)
        embed = panel_embed(
            title=giveaway["prize"],
            color=color.base,
            lines=self._giveaway_embed_lines(end_time, winners, hosts_string, requirements),
            timestamp=False,
        )
        embed.timestamp = giveaway["created_at"]
        await message.edit(embed=embed)
        await ctx.message.add_reaction("👍")

    @giveaway_edit.command(
        name="prize",
        description="Change prize for a giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", prize="New prize name")
    @has_permissions(manage_channels=True)
    async def giveaway_edit_prize(
        self,
        ctx: Context,
        message: discord.Message = None,
        prize: str = None,
    ) -> None:
        """Change prize for a giveaway."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        if not prize:
            await ctx.warn("A prize is required")
            return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        if not giveaway:
            await ctx.warn("That is not a giveaway")
            return
        
        embed = message.embeds[0]
        embed.title = prize
        await message.edit(embed=embed)
        await self.bot.db.execute(
            "UPDATE giveaways SET prize = $1 WHERE message_id = $2",
            prize,
            message.id,
        )
        await ctx.message.add_reaction("👍")

    @giveaway_edit.command(
        name="duration",
        description="Change the end date for a giveaway",
        guild_only=True,
    )
    @describe(message="Giveaway message to edit", duration="Duration in seconds")
    @has_permissions(manage_channels=True)
    async def giveaway_edit_duration(
        self,
        ctx: Context,
        message: discord.Message = None,
        duration: int = None,
    ) -> None:
        """Change the end date for a giveaway."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not message:
                await ctx.warn("A message link is required")
                return
        
        if not duration:
            await ctx.warn("A duration is required")
            return
        
        end_time = datetime.now() + timedelta(seconds=duration)
        try:
            await self.bot.db.execute(
                "UPDATE giveaways SET expiration = $1 WHERE message_id = $2",
                end_time,
                message.id,
            )
        except Exception:
            await ctx.warn("That is not a giveaway")
            return
        
        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message.id,
        )
        end_time = giveaway["expiration"]
        winners = giveaway["winner_count"]
        hosts = []
        for host in giveaway["hosts"]:
            hosts.append(
                self.bot.get_user(host) or await self.bot.fetch_user(host)
            )
        hosts_string = ", ".join(f"{str(m)}" for m in hosts if m is not None)
        requirements = self.get_requirements(giveaway)
        embed = panel_embed(
            title=giveaway["prize"],
            color=color.base,
            lines=self._giveaway_embed_lines(end_time, winners, hosts_string, requirements),
            timestamp=False,
        )
        embed.timestamp = giveaway["created_at"]
        await message.edit(embed=embed)
        await ctx.success(f"Set the expiration of the giveaway to {discord.utils.format_dt(end_time, style='R')}")

    @giveaway.command(
        name="start",
        description="Start a new giveaway",
        guild_only=True,
    )
    @describe(channel="Channel to start giveaway in", duration="Duration in seconds", winners="Number of winners", prize="Prize name")
    @has_permissions(manage_channels=True)
    async def start(
        self,
        ctx: Context,
        channel: discord.TextChannel = None,
        duration: int = 60,
        winners: int = 1,
        prize: str = None,
    ) -> None:
        """Start a new giveaway."""
        if not prize:
            await ctx.warn("A prize is required")
            return
        
        channel = channel or ctx.channel
        end_time = datetime.now() + timedelta(seconds=duration)
        
        embed = panel_embed(
            title=prize,
            color=color.base,
            lines=self._giveaway_embed_lines(end_time, winners, ctx.author.mention),
            timestamp=False,
        )
        embed.timestamp = datetime.now()
        
        message = await channel.send(embed=embed)
        await message.add_reaction("🎉")
        
        await self.bot.db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, expiration, winner_count, hosts, created_at) VALUES($1, $2, $3, $4, $5, $6, $7, $8)",
            ctx.guild.id,
            channel.id,
            message.id,
            prize,
            end_time,
            winners,
            [ctx.author.id],
            datetime.now(),
        )
        
        await ctx.success(f"Giveaway started in {channel.mention}")


async def setup(bot: commands.Bot):
    """Load the Giveaway cog."""
    await bot.add_cog(Giveaway(bot))
