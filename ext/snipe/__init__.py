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



def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def aesthetic_embed(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def reply_embed(
    *,
    color: int,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return aesthetic_embed(color=color, message=message, footer=subtitle, timestamp=False)



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
                embed=reply_embed(
                    color=color.warn,
                    message=f"{emojis.warn} No snipe found at this index.",
                ),
                ephemeral=True,
            )
            return

        if not self.pages:
            await interaction.response.edit_message(
                embed=reply_embed(
                    color=color.base,
                    message=f"{emojis.approve} All snipes cleared for {self.ctx.channel.mention}",
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


def _format_when(ts_raw) -> tuple[str, datetime.datetime]:
    if isinstance(ts_raw, (int, float)):
        ts = datetime.datetime.fromtimestamp(ts_raw, tz=datetime.timezone.utc)
    elif isinstance(ts_raw, datetime.datetime):
        ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=datetime.timezone.utc)
    else:
        ts = datetime.datetime.now(tz=datetime.timezone.utc)
    absolute = discord.utils.format_dt(ts, style="F")
    relative = discord.utils.format_dt(ts, style="R")
    return f"{absolute} · {relative}", ts


def _build_snipe_embed(snipe: dict, index: int, total: int, snipe_type: str) -> discord.Embed:
    content = snipe.get("content") or ""
    if content and any(
        x in content.lower()
        for x in ("discord.gg/", "discord.com/invite", "discordapp.com/invite")
    ):
        content = "*invite link filtered*"

    author = snipe.get("author") or {}
    label = {
        "snipe": "Deleted",
        "editsnipe": "Edited",
        "reactionsnipe": "Reaction",
    }.get(snipe_type, "Deleted")
    when, ts = _format_when(snipe.get("timestamp", 0))

    
    parts = []
    if content:
        parts.append(content)
    else:
        parts.append("*no text content*")
    parts.append("")
    parts.append(f"**{label}:**\n{when}")

    embed = discord.Embed(
        color=color.base,
        description="\n".join(parts),
        timestamp=ts,
    )
    embed.set_footer(text=f"page {index} of {total}")

    if author:
        embed.set_author(
            name=author.get("name") or "Unknown",
            icon_url=author.get("avatar") or None,
        )

    if att := snipe.get("attachments"):
        embed.set_image(url=att[0])
    elif sticks := snipe.get("stickers"):
        embed.set_image(url=sticks[0])

    return embed


async def _send_snipe_pages(
    ctx: Context,
    *,
    kind: str,
    index: int,
    empty_message: str,
) -> None:
    store = ctx.bot.snipes
    try:
        entry, total = await store.get_entry(ctx.channel, type=kind, index=index)
    except SnipeError:
        await ctx.fail(empty_message)
        return

    if total == 1:
        await ctx.send(embed=_build_snipe_embed(entry, 1, 1, kind))
        return

    prefix = store._prefix(kind)
    key = store._key(prefix, ctx.channel.id)
    data = list(store.data.get(key, []))
    pages = [_build_snipe_embed(e, i, total, kind) for i, e in enumerate(data, start=1)]
    view = SnipePaginateView(ctx, pages, kind, store)
    view.index = min(max(index - 1, 0), len(pages) - 1)
    await view.start()


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
        if index < 1:
            index = 1
        await _send_snipe_pages(
            ctx,
            kind="snipe",
            index=index,
            empty_message=f"There are no deleted messages for {ctx.channel.mention}",
        )

    @hybrid(
        name="editsnipe",
        aliases=["es"],
        description="Snipe the latest message that was edited",
        guild_only=True,
    )
    @describe(index="Index of the edit snipe to retrieve")
    async def editsnipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a message's original text before it was edited."""
        if index < 1:
            index = 1
        await _send_snipe_pages(
            ctx,
            kind="editsnipe",
            index=index,
            empty_message=f"There are no edited messages for {ctx.channel.mention}",
        )

    @hybrid(
        name="reactionsnipe",
        aliases=["rs"],
        description="Snipe the latest reaction that was removed",
        guild_only=True,
    )
    @describe(index="Index of the reaction snipe to retrieve")
    async def reactionsnipe(self, ctx: Context, index: int = 1) -> None:
        """Retrieve a deleted reaction from a message."""
        if index < 1:
            index = 1
        try:
            snipe_data = await self.bot.snipes.get_entry(
                ctx.channel, type="reactionsnipe", index=index
            )
        except SnipeError:
            return await ctx.fail(
                f"There are no removed reactions for {ctx.channel.mention}"
            )

        snipe = snipe_data[0]
        total = snipe_data[1]
        reaction = snipe.get("reaction", "")
        if isinstance(reaction, str) and reaction.startswith("https://cdn.discordapp.com/"):
            reaction_display = f"[emoji]({reaction})"
        else:
            reaction_display = str(reaction)

        when, _ = _format_when(snipe.get("timestamp", 0))
        author_name = (snipe.get("author") or {}).get("name", "Unknown")
        jump = snipe.get("message") or ""

        desc = (
            f"**{author_name}** removed {reaction_display}\n\n"
            f"**Removed:**\n{when}"
        )
        if jump:
            desc += f"\n-# [jump to message]({jump})"

        embed = discord.Embed(
            color=color.base,
            description=desc,
        )
        author = snipe.get("author") or {}
        if author.get("avatar"):
            embed.set_author(name=author_name, icon_url=author.get("avatar"))
        else:
            embed.set_author(name=author_name)
        embed.set_footer(text=f"page {index} of {total}")
        await ctx.send(embed=embed)

    @hybrid(
        name="clearsnipe",
        description="Clear all results for reactions, edits and messages",
        guild_only=True,
    )
    @has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx: Context) -> None:
        """Clear all deleted messages from snipe."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        emb = discord.Embed(
            color=color.base,
            description=(
                f"> This will **clear all snipes** for {ctx.channel.mention}.\n"
                f"> Are you sure you want to do this?\n"
                f"-# only {ctx.author.mention} can confirm"
            ),
        )
        if not await view.prompt(embed=emb):
            return await ctx.warn("Clearsnipe **cancelled**")
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

        embed = aesthetic_embed(
            color=color.base,
            title="Reaction history",
            message="",
            timestamp=False,
        )
        embed.url = message.jump_url
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
    from .events import SnipeEvents

    await bot.add_cog(Snipe(bot))
    
    if bot.get_cog("SnipeEvents") is None:
        await bot.add_cog(SnipeEvents(bot))
