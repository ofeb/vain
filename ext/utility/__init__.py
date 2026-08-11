from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import discord
from discord import ui
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe
from core.discord.views.paginate import PaginateView, layout_from_items, send_pages
from config import color, emojis
from core.managers.permissions import has_permissions
from core.tools.snipe import SnipeError

from core.discord.views.embed import c2, reply_embed

if TYPE_CHECKING:
    from .events import SnipeEvents


def _format_when(ts_raw) -> tuple[str, datetime.datetime]:
    if isinstance(ts_raw, datetime.datetime):
        ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=datetime.timezone.utc)
    elif isinstance(ts_raw, (int, float)):
        ts = datetime.datetime.fromtimestamp(float(ts_raw), tz=datetime.timezone.utc)
    else:
        ts = datetime.datetime.now(tz=datetime.timezone.utc)

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    if ts.year > now.year + 1 or ts.year < 2015:
        ts = now
    relative = discord.utils.format_dt(ts, style="R")
    return relative, ts


def _format_clock(ts_raw) -> str:
    """Wall-clock time as zero-padded ``HH:MM`` (local 24h)."""
    _, ts = _format_when(ts_raw)
    local = ts.astimezone()
    return f"{local.hour:02d}:{local.minute:02d}"


def _filter_invites(content: str) -> str:
    text = content or ""
    lower = text.lower()
    if any(
        x in lower
        for x in ("discord.gg/", "discord.com/invite", "discordapp.com/invite")
    ):
        return "*invite link filtered*"
    return text


def _author_name(snipe: dict) -> str:
    author = snipe.get("author") or {}
    return str(author.get("name") or "unknown")


def _author_mention(snipe: dict) -> str:
    author = snipe.get("author") or {}
    uid = author.get("id")
    if uid:
        return f"<@{uid}>"
    return f"**{_author_name(snipe)}**"


def _snipe_accent(bot=None) -> int:
    """Bot base embed color for snipe C2 containers."""
    if bot is not None:
        value = getattr(bot, "color", None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    return int(color.base)


def _build_delete_container(snipe: dict, *, accent: int | None = None) -> ui.Container:
    """Deleted message - mention + deleted this message + relative time."""
    container = ui.Container()
    _ = accent
    when, _ = _format_when(snipe.get("timestamp", 0))
    who = _author_mention(snipe)
    container.add_item(ui.TextDisplay(f"{who} deleted this message {when}"))
    container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

    body = _filter_invites(snipe.get("content") or "")
    if body.strip():
        container.add_item(ui.TextDisplay(body[:3900]))
    else:
        container.add_item(ui.TextDisplay("> -# no text"))

    media = (snipe.get("attachments") or snipe.get("stickers") or [None])[0]
    if media:
        try:
            container.add_item(ui.MediaGallery(discord.MediaGalleryItem(str(media))))
        except Exception:
            container.add_item(ui.TextDisplay(f"[attachment]({media})"))
    return container


def _build_edit_container(snipe: dict, *, accent: int | None = None) -> ui.Container:
    """Edited message card - before/after blocks."""
    container = ui.Container()
    _ = accent
    name = _author_name(snipe)
    when, _ = _format_when(snipe.get("timestamp", 0))
    jump = snipe.get("jump_url") or snipe.get("message") or ""

    container.add_item(ui.TextDisplay(f"Edited message by **{name}**"))
    if jump:
        container.add_item(ui.TextDisplay(f"[Jump to message]({jump}) - {when}"))
    else:
        container.add_item(ui.TextDisplay(f"> -# {when}"))

    container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

    before = _filter_invites(snipe.get("content") or "") or "> -# empty"
    after_raw = snipe.get("after")
    after = (
        _filter_invites(str(after_raw))
        if after_raw is not None
        else "> -# unknown"
    )
    container.add_item(ui.TextDisplay(f"**Before**\n{before[:1800]}"))
    container.add_item(ui.TextDisplay(f"**After**\n{after[:1800]}"))
    return container


def _build_reaction_container(snipe: dict, *, accent: int | None = None) -> ui.Container:
    """Reaction removal - compact quoted line with jump link."""
    container = ui.Container()
    _ = accent
    jump = snipe.get("message") or ""
    reaction = snipe.get("reaction", "")
    if isinstance(reaction, str) and reaction.startswith("https://cdn.discordapp.com/"):
        reaction_display = f"[emoji]({reaction})"
    else:
        reaction_display = str(reaction) if reaction else "?"

    who = _author_mention(snipe)
    if jump:
        msg_bit = f"[`this message`]({jump})"
    else:
        msg_bit = "`a message`"

    container.add_item(
        ui.TextDisplay(f"> -# **{who}** reacted with {reaction_display} to {msg_bit}")
    )
    return container


def _build_snipe_container(
    snipe: dict, kind: str, *, accent: int | None = None
) -> ui.Container:
    if kind == "editsnipe":
        return _build_edit_container(snipe, accent=accent)
    if kind == "reactionsnipe":
        return _build_reaction_container(snipe, accent=accent)
    return _build_delete_container(snipe, accent=accent)


def _snipe_option_label(snipe: dict, kind: str) -> str:
    """Select option title - e.g. ``message deleted by hroe at 5:13``."""
    name = _author_name(snipe)
    clock = _format_clock(snipe.get("timestamp", 0))
    if kind == "editsnipe":
        verb = "message edited by"
    elif kind == "reactionsnipe":
        verb = "reaction removed by"
    else:
        verb = "message deleted by"
    label = f"{verb} {name} at {clock}"
    return label[:100]


def _snipe_search_options(
    data: list[dict], kind: str
) -> list[discord.SelectOption]:
    total = len(data)
    options: list[discord.SelectOption] = []
    for i, snipe in enumerate(data[:25]):
        options.append(
            discord.SelectOption(
                label=_snipe_option_label(snipe, kind),
                value=str(i),
                description=f"page {i + 1}/{total}"[:100],
            )
        )
    return options


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

    prefix = store._prefix(kind)
    key = store._key(prefix, ctx.channel.id)
    data = list(store.data.get(key, []))
    accent = _snipe_accent(ctx.bot)

    
    
    pages = [
        (lambda e=e: _build_snipe_container(e, kind, accent=accent)) for e in data
    ]
    start = min(max(index - 1, 0), max(len(pages) - 1, 0))
    search_options = _snipe_search_options(data, kind)

    async def on_delete_page(page_index: int) -> None:
        try:
            await store.delete_entry(ctx.channel, kind, page_index + 1)
        except SnipeError:
            pass
        
        if 0 <= page_index < len(data):
            try:
                del data[page_index]
            except Exception:
                pass
            try:
                view.search_options = _snipe_search_options(data, kind)
            except Exception:
                pass

    if total == 1:
        layout = layout_from_items([pages[0]()])
        await ctx.send(view=layout)
        return

    view = PaginateView(
        ctx,
        pages,
        start_index=start,
        show_goto=True,
        on_delete_page=on_delete_page,
        search_options=search_options,
        search_title=f"Search for a page (1-{len(pages)})..",
        search_placeholder="select a page to jump to...",
    )
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
        await _send_snipe_pages(
            ctx,
            kind="reactionsnipe",
            index=index,
            empty_message=f"There are no removed reactions for {ctx.channel.mention}",
        )

    @hybrid(
        name="clearsnipe",
        aliases=["cs", "csnipe", "clearsnipes"],
        description="Clear all results for reactions, edits and messages",
        guild_only=True,
    )
    @has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx: Context) -> None:
        """Clear all deleted messages that can be sniped."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        emb = c2(
            message=(
                f"This will **clear all snipes** for {ctx.channel.mention}.\n"
                f"Are you sure you want to do this?"
            ),
            timestamp=False,
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
                await ctx.warn("Please reply to a message or provide a **message ID**\n> -# **usage:** reply to a message or use `,reactionhistory <message_id>`")
                return

        data = await self.bot.db.fetch(
            "SELECT * FROM reaction_history WHERE message_id = $1",
            message.id,
        )

        if not data:
            await ctx.fail(
                f"No reactions logged for that [message]({message.jump_url})\n> -# **reason:** no reaction history found"
            )
            return

        rows = []
        for i, record in enumerate(data, start=1):
            user = self.bot.get_user(record.user_id)
            if not user:
                user = await self.bot.fetch_user(record.user_id)
            rows.append(
                f"`{i}` **{str(user)}** added {str(record.reaction)} "
                f"{discord.utils.format_dt(record.ts, style='R')}"
            )

        embed = c2(
            color=color.base,
            title="Reaction history",
            message="\n".join(rows[:20]),
            timestamp=False,
        )
        embed.url = message.jump_url
        embed.set_author(
            name=str(ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.paginate(embed, rows)

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
            await ctx.fail(f"No snipe found at that index\n> -# **index:** `{index}` — try a smaller number")


async def setup(bot: commands.Bot):
    from .events import SnipeEvents

    await bot.add_cog(Snipe(bot))

    if bot.get_cog("SnipeEvents") is None:
        await bot.add_cog(SnipeEvents(bot))
