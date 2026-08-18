from __future__ import annotations

_CONTEXTS = dict(guilds=True, dms=True, groupchats=True)

import datetime
import re

_LANG = re.compile(r"^[a-zA-Z]{2}(?:-[a-zA-Z]{2})?$")
import io
import contextlib
import asyncio
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import ui
from discord import app_commands
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe
from core.discord.views.paginate import PaginateView, layout_from_items, send_pages
from config import color, emojis
from core.managers.permissions import has_permissions
from core.tools.snipe import SnipeError
from core.tools import image_ops
from core.networks.gemini import GeminiClient
from core.networks import ocr as ocr_net

from core.discord.views.embed import c2, reply_embed, panel_embed

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


def _chunk_text(text: str, size: int = 1800) -> list[str]:
    text = text or ""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:size])
        text = text[size:]
    return chunks


def _is_voice_attachment(att: discord.Attachment) -> bool:
    try:
        if hasattr(att, "is_voice_message") and callable(att.is_voice_message):
            if att.is_voice_message():
                return True
    except Exception:
        pass
    if getattr(att, "duration", None) is not None and getattr(att, "waveform", None) is not None:
        return True
    ctype = (att.content_type or "").lower()
    name = (att.filename or "").lower()
    if ctype.startswith("audio/") or name.endswith((".ogg", ".mp3", ".wav", ".m4a", ".webm")):
        return True
    return False



async def _fetch_bytes(url: str) -> bytes | None:
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception:
        return None
    return None


def _attachment_is_image(att: discord.Attachment) -> bool:
    ctype = (att.content_type or "").lower()
    name = (att.filename or "").lower()
    return ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))


async def _image_from_message(msg: discord.Message) -> tuple[bytes | None, str]:
    for att in msg.attachments:
        if _attachment_is_image(att):
            try:
                return await att.read(), att.filename or "image.png"
            except Exception:
                continue
    for emb in msg.embeds:
        u = getattr(getattr(emb, "image", None), "url", None) or getattr(
            getattr(emb, "thumbnail", None), "url", None
        )
        if u:
            data = await _fetch_bytes(u)
            if data:
                return data, "image.png"
    return None, "image.png"


async def _last_channel_image(channel) -> tuple[bytes | None, str]:
    if channel is None:
        return None, "image.png"
    try:
        async for past in channel.history(limit=50):
            data, name = await _image_from_message(past)
            if data:
                return data, name
    except Exception:
        return None, "image.png"
    return None, "image.png"


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
                await ctx.warn(f"Please reply to a message or provide a **message ID**\n> -# **usage:** reply to a message or use {ctx.cmd('reactionhistory <message_id>')}")
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


class Utility(commands.Cog):
    """Utility builders, ask, translate, OCR."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._menus: list[app_commands.ContextMenu] = []

    def _make_menu(self, name: str, callback) -> app_commands.ContextMenu:
        menu = app_commands.ContextMenu(
            name=name,
            callback=callback,
            type=discord.AppCommandType.message,
        )
        try:
            app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(menu)
        except Exception:
            pass
        try:
            app_commands.allowed_installs(guilds=True, users=True)(menu)
        except Exception:
            pass
        return menu

    async def cog_load(self) -> None:
        specs = (
            ("Quote this message", self.ctx_quote),
            ("Translate this message", self.ctx_translate),
            ("Transcribe this message", self.ctx_transcribe),
            ("Extract Text (OCR)", self.ctx_ocr),
            ("Ask AI about this message", self.ctx_ask),
        )
        for name, callback in specs:
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(name, type=discord.AppCommandType.message)
            menu = self._make_menu(name, callback)
            self.bot.tree.add_command(menu)
            self._menus.append(menu)
        self._ensure_hybrid_contexts()

    def _ensure_hybrid_contexts(self) -> None:
        names = ("ask", "translate", "ocr")
        for name in names:
            cmd = self.bot.tree.get_command(name)
            if cmd is None:
                continue
            try:
                app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(cmd)
            except Exception:
                pass
            try:
                app_commands.allowed_installs(guilds=True, users=True)(cmd)
            except Exception:
                pass

    async def cog_unload(self) -> None:
        for menu in self._menus:
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(menu.name, type=discord.AppCommandType.message)
        self._menus.clear()

    def _gemini(self) -> GeminiClient:
        return GeminiClient()

    async def _ctx_to_context(self, interaction: discord.Interaction) -> Context:
        return await self.bot.get_context(interaction, cls=Context)

    async def ctx_quote(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        if not (message.content or "").strip():
            await interaction.followup.send("That message has no text to quote.", ephemeral=True)
            return
        cog = self.bot.get_cog("Manipulation")
        if cog is None or not hasattr(cog, "_generate_quote_image"):
            await interaction.followup.send("Quote is unavailable right now.", ephemeral=True)
            return
        try:
            avatar_url = str(message.author.display_avatar.with_size(512).url)
            image_data = await cog._generate_quote_image(
                message.clean_content,
                message.author.display_name,
                message.author.name,
                avatar_url,
            )
            file = discord.File(io.BytesIO(image_data), filename="quote.gif")
            await interaction.followup.send(file=file)
            if interaction.guild is not None and hasattr(cog, "_get_quote_channel"):
                dest_id = await cog._get_quote_channel(interaction.guild.id)
                if dest_id and dest_id != getattr(interaction.channel, "id", None):
                    dest = interaction.guild.get_channel(dest_id)
                    if dest is not None and hasattr(dest, "send"):
                        from ext.fun.extended.manipulation import _QuoteChannelView
                        view = _QuoteChannelView(
                            jump_url=message.jump_url,
                            author_id=interaction.user.id,
                        )
                        with contextlib.suppress(Exception):
                            await dest.send(
                                content=(
                                    f"{message.author.mention} · "
                                    f"[Jump to message]({message.jump_url})"
                                ),
                                file=discord.File(io.BytesIO(image_data), filename="quote.gif"),
                                view=view,
                                allowed_mentions=discord.AllowedMentions(users=False),
                            )
        except Exception as exc:
            await interaction.followup.send(f"Couldn't quote that: {exc}", ephemeral=True)

    async def ctx_ask(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        text = (message.content or "").strip()
        if not text:
            await interaction.followup.send("That message has no text to ask about.", ephemeral=True)
            return
        try:
            answer = await self._gemini().prompt(text)
        except Exception as exc:
            await interaction.followup.send(f"Ask failed: {exc}", ephemeral=True)
            return
        if not answer:
            await interaction.followup.send("No response from AI.", ephemeral=True)
            return
        pages = _chunk_text(answer, 1800)
        embeds = []
        qshow = text if len(text) <= 80 else text[:77] + "..."
        for i, chunk in enumerate(pages):
            embeds.append(
                panel_embed(
                    title=f"Answer · {qshow}",
                    lines=[chunk],
                    footer=f"Gemini · {i + 1}/{len(pages)}" if len(pages) > 1 else "Gemini",
                    timestamp=False,
                )
            )
        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0])
        else:
            await interaction.followup.send(embeds=embeds[:10])

    async def ctx_translate(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        text = (message.content or "").strip()
        if not text:
            await interaction.followup.send("That message has no text to translate.", ephemeral=True)
            return
        try:
            result = await self._gemini().translate(text, to_lang="en")
        except Exception as exc:
            await interaction.followup.send(f"Translate failed: {exc}", ephemeral=True)
            return
        out = (result.get("text") if isinstance(result, dict) else str(result or "")).strip()
        detected = (result.get("lang") if isinstance(result, dict) else None) or "Unknown"
        orig = text.replace("`", "'")[:900]
        trans = (out or "*empty*").replace("`", "'")[:1800]
        embed = panel_embed(
            lines=[
                f"**Detected Language**: (`{detected}`)",
                f"> -# `{orig}`",
                "",
                f"**Translated to**: `English`",
                f"> -# `{trans}`",
            ],
            timestamp=False,
        )
        await interaction.followup.send(embed=embed)

    async def ctx_transcribe(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        voice = None
        for att in message.attachments:
            if _is_voice_attachment(att):
                voice = att
                break
        if voice is None:
            await interaction.followup.send("No voice message on that message.", ephemeral=True)
            return
        try:
            audio = await voice.read()
            text = await self._gemini().transcribe_audio(
                audio, mime_type=voice.content_type or "audio/ogg"
            )
        except Exception as exc:
            await interaction.followup.send(f"Transcribe failed: {exc}", ephemeral=True)
            return
        embed = panel_embed(
            title="Transcript",
            lines=[text[:3500] or "*empty transcript*"],
            footer="voice message",
            timestamp=False,
        )
        await interaction.followup.send(embed=embed)

    async def ctx_ocr(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        data = None
        filename = "image.png"
        for att in message.attachments:
            ctype = (att.content_type or "").lower()
            name = (att.filename or "").lower()
            if ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                try:
                    data = await att.read()
                    filename = att.filename or filename
                except Exception:
                    data = None
                break
        if data is None:
            for emb in message.embeds:
                u = getattr(getattr(emb, "image", None), "url", None) or getattr(
                    getattr(emb, "thumbnail", None), "url", None
                )
                if not u:
                    continue
                try:
                    data = await _fetch_bytes(u)
                    if data:
                        break
                except Exception:
                    data = None
        if not data:
            await interaction.followup.send("No image found on that message.", ephemeral=True)
            return
        try:
            text = await ocr_net.ocr_image(data, filename=filename)
        except Exception as exc:
            await interaction.followup.send(f"OCR failed: {exc}", ephemeral=True)
            return
        embed = panel_embed(
            title="Extracted text",
            lines=[text[:3500] or "*no text found*"],
            footer="OCR",
            timestamp=False,
        )
        await interaction.followup.send(embed=embed)

    @hybrid(
        name="ask",
        aliases=["chatgpt", "gemini", "gpt", "ai"],
        description="Ask a question and get results from AI",
        example=",ask what colors make up purple",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(question="Your question")
    async def ask(self, ctx: Context, *, question: str) -> None:
        if not question or not question.strip():
            return await ctx.warn("Ask something")
        async with ctx.typing():
            try:
                answer = await self._gemini().prompt(question.strip())
            except Exception as exc:
                return await ctx.fail(f"AI request failed\n> -# {exc}")
        if not answer:
            return await ctx.warn("No response from AI")
        qshow = question.strip()
        if len(qshow) > 80:
            qshow = qshow[:77] + "..."
        pages = _chunk_text(answer, 1800)
        embeds = []
        for i, chunk in enumerate(pages):
            embeds.append(
                panel_embed(
                    title=f"Answer · {qshow}",
                    lines=[chunk],
                    footer=f"Gemini · {i + 1}/{len(pages)}" if len(pages) > 1 else "Gemini",
                    timestamp=False,
                )
            )
        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await ctx.paginate(embeds)

    @hybrid(
        name="translate",
        aliases=["tr"],
        description="Translate text or a replied message",
        example=",tr es hello",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(payload="Language codes and/or text")
    async def translate(self, ctx: Context, *, payload: str = None) -> None:
        text = None
        to_lang = "en"
        from_lang = None

        tokens = (payload or "").split()
        if tokens and _LANG.match(tokens[0]):
            if len(tokens) >= 2 and _LANG.match(tokens[1]):
                from_lang = tokens[0].lower()
                to_lang = tokens[1].lower()
                text = " ".join(tokens[2:]).strip() or None
            else:
                to_lang = tokens[0].lower()
                text = " ".join(tokens[1:]).strip() or None

        if text is None:
            if ctx.message and ctx.message.reference:
                ref = ctx.message.reference.resolved
                if not isinstance(ref, discord.Message):
                    try:
                        ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    except Exception:
                        ref = None
                if isinstance(ref, discord.Message) and (ref.content or "").strip():
                    text = ref.content.strip()
            if text is None and tokens and not _LANG.match(tokens[0]):
                text = payload.strip() if payload else None

        if not text:
            return await ctx.warn(
                f"Provide text or reply to a message\n> -# **usage:** {ctx.cmd('tr es')} · {ctx.cmd('tr es en hola')}"
            )

        async with ctx.typing():
            try:
                result = await self._gemini().translate(text, to_lang=to_lang, from_lang=from_lang)
            except Exception as exc:
                return await ctx.fail(f"Translate failed\n> -# {exc}")

        out = (result.get("text") if isinstance(result, dict) else str(result or "")).strip()
        detected = (result.get("lang") if isinstance(result, dict) else None) or from_lang or "Unknown"
        if not out:
            return await ctx.warn("Empty translation")

        to_label = (to_lang or "en").lower()
        LANG_NAMES = {
            "en": "English", "es": "Spanish", "fr": "French", "de": "German",
            "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
            "ko": "Korean", "zh": "Chinese", "ar": "Arabic", "hi": "Hindi",
            "tr": "Turkish", "nl": "Dutch", "pl": "Polish", "sv": "Swedish",
        }
        to_name = LANG_NAMES.get(
            to_label,
            to_lang.upper() if to_lang and len(to_lang) <= 3 else str(to_lang).title(),
        )
        if from_lang:
            from_name = LANG_NAMES.get(
                from_lang.lower(),
                from_lang.upper() if len(from_lang) <= 3 else from_lang.title(),
            )
            head = f"> **{from_name}**"
        else:
            head = f"> **Detected Language**: (`{detected}`)"
        orig = text.replace("`", "'")[:900]
        trans = out.replace("`", "'")[:1800]
        lines = [
            head,
            f"> -# `{orig}`",
            "",
            f"> **Translated to**: `{to_name}`",
            f"> -# `{trans}`",
        ]
        embed = panel_embed(lines=lines, timestamp=False)
        return await ctx.send(embed=embed)

    @commands.command(
        name="transcribe",
        aliases=["ts", "transcript"],
        description="Transcribe a Discord voice message",
    )
    async def transcribe(self, ctx: Context, message: discord.Message = None) -> None:
        voice = None
        source = None

        candidates: list[discord.Message] = []
        if message is not None:
            candidates.append(message)
        if ctx.message and ctx.message.reference:
            ref = ctx.message.reference.resolved
            if not isinstance(ref, discord.Message):
                try:
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                except Exception:
                    ref = None
            if isinstance(ref, discord.Message):
                candidates.append(ref)

        for msg in candidates:
            for att in msg.attachments:
                if _is_voice_attachment(att):
                    voice = att
                    source = msg
                    break
            if voice:
                break

        if voice is None and ctx.channel is not None:
            skip = ctx.message.id if ctx.message else None
            try:
                async for past in ctx.channel.history(limit=50):
                    if skip and past.id == skip:
                        continue
                    for att in past.attachments:
                        if _is_voice_attachment(att):
                            voice = att
                            source = past
                            break
                    if voice:
                        break
            except Exception:
                pass

        if voice is None or source is None:
            return await ctx.warn(
                f"No voice message found\n> -# **usage:** reply to a voice memo or run {ctx.cmd('transcribe')}"
            )

        async with ctx.typing():
            try:
                audio = await voice.read()
                text = await self._gemini().transcribe_audio(
                    audio, mime_type=voice.content_type or "audio/ogg"
                )
            except Exception as exc:
                return await ctx.fail(f"Transcribe failed\n> -# {exc}")

        embed = panel_embed(
            title="Transcript",
            lines=[text[:3500] or "*empty transcript*"],
            footer="voice message",
            timestamp=False,
        )
        try:
            return await ctx.reply(embed=embed, mention_author=False)
        except Exception:
            return await ctx.send(embed=embed)

    @hybrid(
        name="ocr",
        aliases=["extracttext", "readimage"],
        description="Extract text from an image (OCR)",
        example=",ocr",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(image="Image to extract text from", url="Image URL")
    async def ocr(
        self,
        ctx: Context,
        image: discord.Attachment | None = None,
        url: str | None = None,
    ) -> None:
        data = None
        filename = "image.png"
        slash = bool(getattr(ctx, "interaction", None))

        if image is not None:
            try:
                data = await image.read()
                filename = image.filename or filename
            except Exception:
                data = None
        if data is None and url:
            data = await _fetch_bytes(str(url).strip())
        if data is None and ctx.message and ctx.message.attachments:
            for att in ctx.message.attachments:
                if _attachment_is_image(att):
                    data = await att.read()
                    filename = att.filename or filename
                    break
        if data is None and ctx.message and ctx.message.reference:
            try:
                ref = ctx.message.reference.resolved
                if not isinstance(ref, discord.Message):
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if isinstance(ref, discord.Message):
                    data, filename = await _image_from_message(ref)
            except Exception:
                data = None
        if data is None and not slash:
            data, filename = await _last_channel_image(ctx.channel)

        if not data:
            msg = (
                f"You need to add an attachment or provide a url\n"
                f"> -# **usage:** {ctx.cmd('ocr')} with an image"
            )
            return await ctx.warn(msg)

        async with ctx.typing():
            try:
                text = await ocr_net.ocr_image(data, filename=filename)
            except Exception as exc:
                return await ctx.fail(f"OCR failed\n> -# {exc}")

        embed = panel_embed(
            title="Extracted text",
            lines=[text[:3500] or "*no text found*"],
            footer="OCR",
            timestamp=False,
        )
        return await ctx.send(embed=embed)


    @hybrid(
        name="embedbuilder",
        aliases=["eb"],
        description="Interactive embed builder with live preview. Approve DMs the script.",
        example=",embedbuilder",
    )
    @has_permissions(manage_messages=True)
    async def embedbuilder(self, ctx: Context):
        from .improper.builders import EmbedBuilderView
        accent = getattr(ctx.bot, "color", None) or 0x2B2D31
        builder = EmbedBuilderView(ctx.author.id, accent=int(accent))
        m = await ctx.send(
            embed=builder._preview_embed(),
            view=builder._embed_preview_view(),
            raw_embed=True,
        )
        builder.message = m

    @hybrid(
        name="containerbuilder",
        aliases=["cb"],
        description="Interactive Components V2 container builder with live preview. Approve DMs the script.",
        example=",containerbuilder",
    )
    @has_permissions(manage_messages=True)
    async def containerbuilder(self, ctx: Context):
        from .improper.builders import ContainerBuilderView
        accent = getattr(ctx.bot, "color", None) or 0x2B2D31
        builder = ContainerBuilderView(ctx.author.id, accent=int(accent))
        preview_content, preview_layout = builder._preview_container()
        await builder._refresh_content_message(preview_content, ctx.channel)
        m = await ctx.send(view=builder._controls())
        builder.message = m
        try:
            preview = await ctx.send(content=None, view=preview_layout)
            builder.preview_message = preview
        except Exception:
            builder.preview_message = None


async def setup(bot: commands.Bot):
    from .events import SnipeEvents

    await bot.add_cog(Snipe(bot))
    await bot.add_cog(Utility(bot))

    if bot.get_cog("SnipeEvents") is None:
        await bot.add_cog(SnipeEvents(bot))
