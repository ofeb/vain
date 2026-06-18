from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe
from core.managers.values import color

if TYPE_CHECKING:
    from .events import SnipeEvents


class Snipe(commands.Cog):
    """Message sniping system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="snipe",
        description="Snipe the latest message that was deleted",
        guild_only=True,
    )
    @describe(index="Index of the snipe to retrieve")
    async def snipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a recently deleted message."""
        snipe = await self.bot.snipes.get_entry(ctx.channel, type="snipe", index=index)
        if not snipe:
            await ctx.fail(f"There are no deleted messages for {ctx.channel.mention}")
            return
        
        total = snipe[1]
        snipe = snipe[0]
        
        content = snipe.get("content")
        if content:
            if any(x in content.lower() for x in ["discord.gg/", "discord.com/", "discordapp.com/"]):
                await ctx.fail("snipe had filtered content")
                return
            content = "".join(c for c in content if c.isalnum() or c.isspace())
            if "discord.gg" in content.lower() or "discord.com/" in content.lower() or "discordapp.com" in content.lower():
                await ctx.fail("snipe had filtered content")
                return
        
        embed = discord.Embed(
            color=color.base,
            description=content or (snipe["embeds"][0].get("description") if snipe.get("embeds") else ""),
            timestamp=datetime.fromtimestamp(snipe.get("timestamp")),
        )
        
        embed.set_author(
            name=snipe.get("author").get("name"),
            icon_url=snipe.get("author").get("avatar"),
        )
        
        if att := snipe.get("attachments"):
            embed.set_image(url=att[0])
        elif sticks := snipe.get("stickers"):
            embed.set_image(url=sticks[0])
        
        embed.set_footer(text=f"Deleted {discord.utils.format_dt(snipe.get('timestamp'), style='R')} | {index}/{total}")
        
        await ctx.send(embed=embed)

    @hybrid(
        name="editsnipe",
        description="Snipe the latest message that was edited",
        guild_only=True,
    )
    @describe(index="Index of the edit snipe to retrieve")
    async def editsnipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a message's original text before edited."""
        snipe = await self.bot.snipes.get_entry(ctx.channel, type="editsnipe", index=index)
        if not snipe:
            await ctx.fail("There is nothing to snipe")
            return
        
        total = snipe[1]
        snipe = snipe[0]
        
        content = snipe.get("content")
        if content:
            if any(x in content.lower() for x in ["discord.gg/", "discord.com/", "discordapp.com/"]):
                await ctx.fail("snipe had filtered content")
                return
            content = "".join(c for c in content if c.isalnum() or c.isspace())
            if "discord.gg" in content.lower() or "discord.com/" in content.lower() or "discordapp.com" in content.lower():
                await ctx.fail("snipe had filtered content")
                return
        
        embed = discord.Embed(
            color=color.base,
            description=content or ("Message contains an embed" if snipe.get("embeds") else ""),
            timestamp=datetime.fromtimestamp(snipe.get("timestamp")),
        )
        
        embed.set_author(
            name=snipe.get("author").get("name"),
            icon_url=snipe.get("author").get("avatar"),
        )
        
        if att := snipe.get("attachments"):
            embed.set_image(url=att[0])
        elif sticks := snipe.get("stickers"):
            embed.set_image(url=sticks[0])
        
        embed.set_footer(
            text=f"Edited {discord.utils.format_dt(snipe.get('timestamp'), style='R')} | {index}/{total}",
            icon_url=ctx.author.display_avatar,
        )
        
        await ctx.send(embed=embed)

    @hybrid(
        name="reactionsnipe",
        description="Snipe the latest reaction that was removed",
        guild_only=True,
    )
    @describe(index="Index of the reaction snipe to retrieve")
    async def reactionsnipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a deleted reaction from a message."""
        snipe = await self.bot.snipes.get_entry(ctx.channel, type="reactionsnipe", index=index)
        if not snipe:
            await ctx.fail("There is nothing to snipe")
            return
        
        snipe = snipe[0]
        reaction = snipe.get("reaction")
        reaction_display = reaction if not reaction.startswith("https://cdn.discordapp.com/") else str(reaction)
        
        embed = discord.Embed(
            color=color.base,
            description=f"**{snipe.get('author').get('name')}** reacted with {reaction_display} <t:{int(snipe.get('timestamp'))}:R>",
        )
        
        await ctx.send(embed=embed)

    @hybrid(
        name="clearsnipe",
        description="Clear all results for reactions, edits and messages",
        guild_only=True,
    )
    @commands.has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx: Context) -> None:
        """Clear all deleted messages from snipe."""
        await self.bot.snipes.clear_entries(ctx.channel)
        await ctx.success(f"Cleared snipes for {ctx.channel.mention}")

    @hybrid(
        name="reactionhistory",
        description="See logged reactions for a message",
        guild_only=True,
    )
    @describe(message="Message to get reaction history for")
    async def reactionhistory(self, ctx: Context, message: discord.Message = None) -> None:
        """See logged reactions for a message."""
        if not message:
            if ctx.message.reference:
                message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            else:
                await ctx.fail("You must reply or provide a message id")
                return
        
        data = await self.bot.db.fetch(
            "SELECT * FROM reaction_history WHERE message_id = $1",
            message.id,
        )
        
        if not data:
            await ctx.fail(f"No reactions logged for the [message]({message.jump_url}) provided")
            return
        
        rows = []
        for i, record in enumerate(data, start=1):
            user = self.bot.get_user(record.user_id)
            if not user:
                user = await self.bot.fetch_user(record.user_id)
            rows.append(f"`{i}` **{str(user)}** added {str(record.reaction)} {discord.utils.format_dt(record.ts, style='R')}")
        
        embed = discord.Embed(
            title="Reaction history",
            url=message.jump_url,
            color=color.base,
        )
        embed.set_author(
            name=str(ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        
        await ctx.send(embed=embed)

    @hybrid(
        name="removesnipe",
        description="Remove a snipe from the snipe index",
        guild_only=True,
    )
    @describe(index="Index of the snipe to remove")
    @commands.has_permissions(manage_messages=True)
    async def removesnipe(self, ctx: Context, index: int = 1) -> None:
        """Remove a snipe from the snipe index."""
        try:
            await self.bot.snipes.delete_entry(ctx.channel, "snipe", index)
            await ctx.success(f"Deleted snipe at index `{index}`")
        except Exception:
            await ctx.fail(f"No snipe found at index `{index}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(Snipe(bot))
