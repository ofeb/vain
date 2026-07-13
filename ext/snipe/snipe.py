from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe
from core.discord.views.paginate import PaginateView
from core.managers.values import color, emojis
from core.managers.permissions import has_permissions
from core.tools.snipe import SnipeError

if TYPE_CHECKING:
    from .events import SnipeEvents


class SnipePaginateView(PaginateView):
    def __init__(self, ctx: Context, pages: list[discord.Embed], snipe_type: str, snipe_store):
        super().__init__(ctx, pages)
        self.snipe_type = snipe_type
        self.snipe_store = snipe_store
        remove_btn = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            emoji=discord.PartialEmoji.from_str(emojis.remove),
        )
        remove_btn.callback = self._remove_cb
        self.add_item(remove_btn)

    async def _remove_cb(self, interaction: discord.Interaction) -> None:
        try:
            await self.snipe_store.delete_entry(self.ctx.channel, self.snipe_type, self.index + 1)
            del self.pages[self.index]
        except SnipeError:
            await interaction.response.send_message(
                embed=discord.Embed(
                    color=color.warn,
                    description=f"{emojis.warn} No snipe found at this index.",
                ),
                ephemeral=True,
            )
            return

        if not self.pages:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    color=color.base,
                    description=f"{emojis.approve} All snipes cleared for {self.ctx.channel.mention}",
                ),
                view=None,
            )
            self.stop()
            return

        self.index = min(self.index, len(self.pages) - 1)
        payload = self._current()
        if not self.pages:
            payload["view"] = None
        await interaction.response.edit_message(**payload)


def _build_snipe_embed(snipe: dict, index: int, total: int, snipe_type: str) -> discord.Embed:
    content = snipe.get("content", "")
    if content:
        if any(x in content.lower() for x in ["discord.gg/", "discord.com/", "discordapp.com/"]):
            content = "*snipe had filtered content*"

    embed = discord.Embed(
        color=color.base,
        description=content or "",
        timestamp=datetime.datetime.fromtimestamp(snipe.get("timestamp", 0)),
    )

    author = snipe.get("author", {})
    if author:
        embed.set_author(
            name=author.get("name", "Unknown"),
            icon_url=author.get("avatar", ""),
        )

    if att := snipe.get("attachments"):
        embed.set_image(url=att[0])
    elif sticks := snipe.get("stickers"):
        embed.set_image(url=sticks[0])

    label = {"snipe": "Deleted", "editsnipe": "Edited", "reactionsnipe": "Reaction"}.get(snipe_type, "Deleted")
    ts = snipe.get("timestamp", 0)
    if isinstance(ts, (int, float)):
        ts = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    diff = now - ts
    if diff.total_seconds() < 86400 and ts.day == now.day:
        time_str = f"today at {discord.utils.format_dt(ts, style='t')}"
    elif diff.total_seconds() < 172800 and ts.day == now.day - 1:
        time_str = f"yesterday at {discord.utils.format_dt(ts, style='t')}"
    else:
        time_str = discord.utils.format_dt(ts, style='f')
    embed.set_footer(text=f"{label} {time_str} \u2219 {index}/{total} \u2219 Module: utility")

    return embed


class Snipe(commands.Cog):
    """Message sniping system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="snipe",
        aliases=["s"],
        description="Snipe the latest message that was deleted",
        guild_only=True,
    )
    @describe(index="Index of the snipe to retrieve")
    async def snipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve recently deleted messages."""
        try:
            snipe_data = await self.bot.snipes.get_entry(ctx.channel, type="snipe", index=index)
        except SnipeError:
            return await ctx.fail(f"There are no deleted messages for {ctx.channel.mention}")

        total = snipe_data[1]
        store = self.bot.snipes

        if total == 1:
            snipe = snipe_data[0]
            embed = _build_snipe_embed(snipe, 1, 1, "snipe")
            return await ctx.send(embed=embed)

        pages = []
        prefix = "s-"
        key = store._key(prefix, ctx.channel.id)
        data = store.data.get(key, [])
        for i, entry in enumerate(data, start=1):
            pages.append(_build_snipe_embed(entry, i, total, "snipe"))

        view = SnipePaginateView(ctx, pages, "snipe", store)
        view.index = min(index - 1, len(pages) - 1)
        await view.start()

    @hybrid(
        name="editsnipe",
        aliases=["es"],
        description="Snipe the latest message that was edited",
        guild_only=True,
    )
    @describe(index="Index of the edit snipe to retrieve")
    async def editsnipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a message's original text before edited."""
        try:
            snipe_data = await self.bot.snipes.get_entry(ctx.channel, type="editsnipe", index=index)
        except SnipeError:
            return await ctx.warn("There is nothing to snipe")

        total = snipe_data[1]
        store = self.bot.snipes

        if total == 1:
            snipe = snipe_data[0]
            embed = _build_snipe_embed(snipe, 1, 1, "editsnipe")
            return await ctx.send(embed=embed)

        pages = []
        prefix = "es-"
        key = store._key(prefix, ctx.channel.id)
        data = store.data.get(key, [])
        for i, entry in enumerate(data, start=1):
            pages.append(_build_snipe_embed(entry, i, total, "editsnipe"))

        view = SnipePaginateView(ctx, pages, "editsnipe", store)
        view.index = min(index - 1, len(pages) - 1)
        await view.start()

    @hybrid(
        name="reactionsnipe",
        aliases=["rs"],
        description="Snipe the latest reaction that was removed",
        guild_only=True,
    )
    @describe(index="Index of the reaction snipe to retrieve")
    async def reactionsnipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a deleted reaction from a message."""
        try:
            snipe_data = await self.bot.snipes.get_entry(ctx.channel, type="reactionsnipe", index=index)
        except SnipeError:
            return await ctx.warn("There is nothing to snipe")

        snipe = snipe_data[0]
        total = snipe_data[1]
        reaction = snipe.get("reaction", "")
        reaction_display = reaction if not reaction.startswith("https://cdn.discordapp.com/") else str(reaction)

        ts_raw = snipe.get("timestamp", 0)
        ts = datetime.datetime.fromtimestamp(ts_raw, tz=datetime.timezone.utc) if isinstance(ts_raw, (int, float)) else ts_raw
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        diff = now - ts
        if diff.total_seconds() < 86400 and ts.day == now.day:
            time_str = f"today at {discord.utils.format_dt(ts, style='t')}"
        elif diff.total_seconds() < 172800 and ts.day == now.day - 1:
            time_str = f"yesterday at {discord.utils.format_dt(ts, style='t')}"
        else:
            time_str = discord.utils.format_dt(ts, style='f')

        embed = discord.Embed(
            color=color.base,
            description=f"**{snipe.get('author', {}).get('name', 'Unknown')}** reacted with {reaction_display} {time_str}",
        )
        embed.set_footer(text=f"Reaction \u2219 {index}/{total} \u2219 Module: utility")

        await ctx.send(embed=embed)

    @hybrid(
        name="clearsnipe",
        description="Clear all results for reactions, edits and messages",
        guild_only=True,
    )
    @has_permissions(manage_messages=True)
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
                await ctx.warn("You must reply or provide a message id")
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
    @has_permissions(manage_messages=True)
    async def removesnipe(self, ctx: Context, index: int = 1) -> None:
        """Remove a snipe from the snipe index."""
        try:
            await self.bot.snipes.delete_entry(ctx.channel, "snipe", index)
            await ctx.success(f"Deleted snipe at index `{index}`")
        except SnipeError:
            await ctx.fail(f"No snipe found at index `{index}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(Snipe(bot))
