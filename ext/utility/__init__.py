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

_LANG_CHOICES = [
    ("Afrikaans", "af"),
    ("Albanian", "sq"),
    ("Amharic", "am"),
    ("Arabic", "ar"),
    ("Armenian", "hy"),
    ("Assamese", "as"),
    ("Aymara", "ay"),
    ("Azerbaijani", "az"),
    ("Bambara", "bm"),
    ("Basque", "eu"),
    ("Belarusian", "be"),
    ("Bengali", "bn"),
    ("Bhojpuri", "bho"),
    ("Bosnian", "bs"),
    ("Bulgarian", "bg"),
    ("Catalan", "ca"),
    ("Cebuano", "ceb"),
    ("Chinese (Simplified)", "zh-CN"),
    ("Chinese (Traditional)", "zh-TW"),
    ("Corsican", "co"),
    ("Croatian", "hr"),
    ("Czech", "cs"),
    ("Danish", "da"),
    ("Dhivehi", "dv"),
    ("Dogri", "doi"),
    ("Dutch", "nl"),
    ("English", "en"),
    ("Esperanto", "eo"),
    ("Estonian", "et"),
    ("Ewe", "ee"),
    ("Filipino", "fil"),
    ("Finnish", "fi"),
    ("French", "fr"),
    ("Frisian", "fy"),
    ("Galician", "gl"),
    ("Georgian", "ka"),
    ("German", "de"),
    ("Greek", "el"),
    ("Guarani", "gn"),
    ("Gujarati", "gu"),
    ("Haitian Creole", "ht"),
    ("Hausa", "ha"),
    ("Hawaiian", "haw"),
    ("Hebrew", "he"),
    ("Hindi", "hi"),
    ("Hmong", "hmn"),
    ("Hungarian", "hu"),
    ("Icelandic", "is"),
    ("Igbo", "ig"),
    ("Ilocano", "ilo"),
    ("Indonesian", "id"),
    ("Irish", "ga"),
    ("Italian", "it"),
    ("Japanese", "ja"),
    ("Javanese", "jv"),
    ("Kannada", "kn"),
    ("Kazakh", "kk"),
    ("Khmer", "km"),
    ("Kinyarwanda", "rw"),
    ("Konkani", "gom"),
    ("Korean", "ko"),
    ("Krio", "kri"),
    ("Kurdish", "ku"),
    ("Kurdish (Sorani)", "ckb"),
    ("Kyrgyz", "ky"),
    ("Lao", "lo"),
    ("Latin", "la"),
    ("Latvian", "lv"),
    ("Lingala", "ln"),
    ("Lithuanian", "lt"),
    ("Luganda", "lg"),
    ("Luxembourgish", "lb"),
    ("Macedonian", "mk"),
    ("Maithili", "mai"),
    ("Malagasy", "mg"),
    ("Malay", "ms"),
    ("Malayalam", "ml"),
    ("Maltese", "mt"),
    ("Maori", "mi"),
    ("Marathi", "mr"),
    ("Meiteilon (Manipuri)", "mni-Mtei"),
    ("Mizo", "lus"),
    ("Mongolian", "mn"),
    ("Myanmar (Burmese)", "my"),
    ("Nepali", "ne"),
    ("Norwegian", "no"),
    ("Nyanja (Chichewa)", "ny"),
    ("Odia (Oriya)", "or"),
    ("Oromo", "om"),
    ("Pashto", "ps"),
    ("Persian", "fa"),
    ("Polish", "pl"),
    ("Portuguese", "pt"),
    ("Punjabi", "pa"),
    ("Quechua", "qu"),
    ("Romanian", "ro"),
    ("Russian", "ru"),
    ("Samoan", "sm"),
    ("Sanskrit", "sa"),
    ("Scots Gaelic", "gd"),
    ("Serbian", "sr"),
    ("Sesotho", "st"),
    ("Shona", "sn"),
    ("Sindhi", "sd"),
    ("Sinhala", "si"),
    ("Slovak", "sk"),
    ("Slovenian", "sl"),
    ("Somali", "so"),
    ("Spanish", "es"),
    ("Sundanese", "su"),
    ("Swahili", "sw"),
    ("Swedish", "sv"),
    ("Tagalog", "tl"),
    ("Tajik", "tg"),
    ("Tamil", "ta"),
    ("Tatar", "tt"),
    ("Telugu", "te"),
    ("Thai", "th"),
    ("Tigrinya", "ti"),
    ("Tsonga", "ts"),
    ("Turkish", "tr"),
    ("Turkmen", "tk"),
    ("Twi (Akan)", "ak"),
    ("Ukrainian", "uk"),
    ("Urdu", "ur"),
    ("Uyghur", "ug"),
    ("Uzbek", "uz"),
    ("Vietnamese", "vi"),
    ("Welsh", "cy"),
    ("Xhosa", "xh"),
    ("Yiddish", "yi"),
    ("Yoruba", "yo"),
    ("Zulu", "zu"),
]

def _lang_choice_label(name: str, code: str) -> str:
    return f"{name} ({code})"


def _lang_autocomplete_choices(current: str, *, include_auto: bool = False) -> list[app_commands.Choice[str]]:
    """Filter languages by typed needle; always return at most 25 (Discord limit)."""
    needle = (current or "").strip().lower()
    out: list[app_commands.Choice[str]] = []
    if include_auto:
        auto_label = "Auto-detect (auto)"
        if not needle or needle in auto_label.lower() or needle in ("auto", "detect"):
            out.append(app_commands.Choice(name=auto_label, value="auto"))
    for name, code in _LANG_CHOICES:
        label = _lang_choice_label(name, code)
        if not needle or needle in name.lower() or needle in code.lower() or needle in label.lower():
            out.append(app_commands.Choice(name=label, value=code))
        if len(out) >= 25:
            break
    
    if needle and _LANG.match(needle) and not any(c.value.lower() == needle for c in out):
        for name, code in _LANG_CHOICES:
            if code.lower() == needle:
                out = [app_commands.Choice(name=_lang_choice_label(name, code), value=code)] + out
                out = out[:25]
                break
        else:
            
            out = [app_commands.Choice(name=f"{needle} ({needle})", value=needle)] + out
            out = out[:25]
    return out[:25]


_LANG_NAME_BY_CODE = {code: name for name, code in _LANG_CHOICES}
_LANG_CODE_BY_NAME = {name.lower(): code for name, code in _LANG_CHOICES}


def _lang_display(code_or_name: str | None) -> str:
    if not code_or_name:
        return "Unknown"
    raw = str(code_or_name).strip()
    low = raw.lower()
    if low in _LANG_NAME_BY_CODE:
        return _LANG_NAME_BY_CODE[low]
    for n, c in _LANG_CHOICES:
        if n.lower() == low:
            return n
    if low in _LANG_CODE_BY_NAME:
        return next(n for n, c in _LANG_CHOICES if c == _LANG_CODE_BY_NAME[low])
    return raw.title() if len(raw) > 3 else raw.upper()


def _lang_code(code_or_name: str | None, default: str = "auto") -> str:
    if not code_or_name:
        return default
    raw = str(code_or_name).strip()
    low = raw.lower()
    if low in {"auto", "detect", "none", "unknown"}:
        return default
    if low in _LANG_NAME_BY_CODE:
        return low
    for n, c in _LANG_CHOICES:
        if n.lower() == low:
            return c
    if low in _LANG_CODE_BY_NAME:
        return _LANG_CODE_BY_NAME[low]
    if len(low) <= 3 and low.isalpha():
        return low
    return default


def _google_translate_url(text: str, *, source: str, target: str) -> str:
    from urllib.parse import quote

    sl = _lang_code(source, "auto")
    tl = _lang_code(target, "en")
    return (
        "https://translate.google.com/details?"
        f"sl={quote(sl)}&tl={quote(tl)}&op=translate&text={quote(text or '', safe='')}"
    )


def _translate_layout(
    *,
    original: str,
    translated: str,
    from_label: str,
    to_label: str,
    source_code: str,
    target_code: str,
):
    from discord import ui
    from core.tools.embed import _make_separator

    layout = ui.LayoutView(timeout=None)
    container = ui.Container()
    for _attr in ("accent_color", "accent_colour"):
        if hasattr(container, _attr):
            try:
                setattr(container, _attr, None)
            except Exception:
                pass

    title = "# <a:messages:1539180118801383424> **Translation**"
    direction = f"-# {from_label} → {to_label}"
    orig = (original or "").strip()
    if len(orig) > 1800:
        orig = orig[:1797] + "..."
    trans = (translated or "").strip()
    if len(trans) > 1800:
        trans = trans[:1797] + "..."


    orig_block = f"`{orig}`"
    container.add_item(ui.TextDisplay(f"{title}\n{direction}\n\n{orig_block}"))
    container.add_item(_make_separator(visible=True, spacing=1))

    container.add_item(ui.TextDisplay(f"`{trans}`"))

    url = _google_translate_url(original, source=source_code, target=target_code)
    try:
        btn = ui.Button(
            label="Open in Google Translate",
            style=discord.ButtonStyle.link,
            url=url[:512],
        )
        container.add_item(ui.ActionRow(btn))
    except Exception:
        container.add_item(ui.TextDisplay(f"[Open in Google Translate]({url})"))

    layout.add_item(container)
    return layout


from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import command, describe, hybrid
from .extended.remind import Remind
from core.discord.views.paginate import PaginateView, layout_from_items, send_pages
from config import api, color, emojis
from core.managers.permissions import has_permissions
from core.tools.snipe import SnipeError
from core.tools import image_ops
from core.networks.gemini import GeminiClient
from core.networks.translate import GoogleTranslateClient
from core.networks.transcribe import WhisperTranscribeClient
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

    urls = []
    for link in (snipe.get("attachments") or []):
        if link:
            urls.append(str(link))
    for link in (snipe.get("stickers") or []):
        if link and str(link) not in urls:
            urls.append(str(link))
    if urls:
        try:
            items = [discord.MediaGalleryItem(url) for url in urls[:10]]
            container.add_item(ui.MediaGallery(*items))
        except Exception:
            for url in urls[:5]:
                container.add_item(ui.TextDisplay(f"[attachment]({url})"))
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
    urls = []
    for link in (snipe.get("attachments") or []):
        if link:
            urls.append(str(link))
    for link in (snipe.get("stickers") or []):
        if link and str(link) not in urls:
            urls.append(str(link))
    if urls:
        try:
            items = [discord.MediaGalleryItem(url) for url in urls[:10]]
            container.add_item(ui.MediaGallery(*items))
        except Exception:
            for url in urls[:5]:
                container.add_item(ui.TextDisplay(f"[attachment]({url})"))
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
    """Split text into pages without cutting mid-word or mid-paragraph when possible."""
    text = (text or "").strip()
    if not text:
        return [""]
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= size:
            chunks.append(remaining.strip())
            break
        window = remaining[: size + 1]
        cut = -1
        
        para = window.rfind("\n\n")
        if para >= int(size * 0.45):
            cut = para
        else:
            
            line = window.rfind("\n")
            if line >= int(size * 0.55):
                cut = line
            else:
                
                for sep in (". ", "! ", "? ", "。", "…"):
                    idx = window.rfind(sep)
                    if idx >= int(size * 0.55):
                        cut = idx + len(sep) - 1
                        break
                if cut < 0:
                    
                    sp = window.rfind(" ")
                    if sp >= int(size * 0.4):
                        cut = sp
        if cut < 1:
            cut = size
        piece = remaining[: cut + 1].rstrip()
        if not piece:
            piece = remaining[:size]
            cut = size - 1
        chunks.append(piece)
        remaining = remaining[cut + 1 :].lstrip()
    return [c for c in chunks if c]


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



def _gemini_model() -> str:
    return getattr(api, "gemini_model", None) or getattr(api, "llm", None) or "Gemini"


def _is_gif(data: bytes | None, filename: str = "") -> bool:
    name = (filename or "").lower()
    if name.endswith(".gif"):
        return True
    if data and data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False

def _ocr_embed(text: str):
    body = (text or "").strip() or "no text found"
    body = body.replace(">", "")
    if len(body) > 1900:
        body = body[:1900]
    return c2(message=f"```{body}```", footer=" Engine 2")

def _transcribe_embed(text: str):
    body = (text or "").strip() or "empty transcript"
    body = body.replace(">", "")
    if len(body) > 1900:
        body = body[:1900]
    return c2(message=f"```{body}```", footer=f" {_gemini_model()}")


def _ask_embed(text: str, *, page: int | None = None, total: int | None = None):
    footer = f" {_gemini_model()}"
    if page is not None and total is not None and total > 1:
        footer = f" {_gemini_model()} · {page}/{total}"
    return c2(message=text, footer=footer)


def _ask_pages(answer: str) -> list:
    chunks = _chunk_text(answer, 1800)
    total = len(chunks) or 1
    return [
        _ask_embed(chunk, page=i + 1, total=total)
        for i, chunk in enumerate(chunks or [""])
    ]


class Snipe(commands.Cog):
    """Message sniping system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="snipe",
        aliases=["s"],
        description="snipe the latest message that was deleted",
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
        description="snipe the latest message that was edited",
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
        description="snipe the latest reaction that was removed",
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
        description="clear all results for reactions, edits and messages",
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
        description="see logged reactions for a message",
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
        description="remove a snipe from the snipe index",
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


class Utility(Remind):
    """Utility builders, ask, translate, OCR, reminders."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
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
        await super().cog_load()

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
            if name == "translate":
                try:
                    params = list(getattr(cmd, "parameters", []) or [])
                    
                    hybrid_cmd = self.bot.get_command("translate")
                    app = getattr(hybrid_cmd, "app_command", None) if hybrid_cmd else None
                    if app is not None:
                        params = list(getattr(app, "parameters", []) or params)
                    for param in params:
                        pname = getattr(param, "name", None)
                        if pname == "text":
                            param.required = True
                        elif pname in ("to", "from", "source"):
                            param.required = False
                except Exception:
                    pass

    async def cog_unload(self) -> None:
        for menu in self._menus:
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(menu.name, type=discord.AppCommandType.message)
        self._menus.clear()
        await super().cog_unload()

    def _gemini(self) -> GeminiClient:
        return GeminiClient()

    def _translator(self) -> GoogleTranslateClient:
        return GoogleTranslateClient()

    def _transcriber(self) -> WhisperTranscribeClient:
        return WhisperTranscribeClient(self.bot)

    async def _transcribe_bytes(self, audio: bytes, *, mime_type: str = "audio/ogg") -> str:
        try:
            return await self._transcriber().transcribe_audio(audio, mime_type=mime_type)
        except Exception:
            return await self._gemini().transcribe_audio(audio, mime_type=mime_type)

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
        pages = _ask_pages(answer)
        ctx = await self.bot.get_context(interaction, cls=Context)
        await send_pages(ctx, pages)

    async def ctx_translate(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        text = (message.content or "").strip()
        if not text:
            await interaction.followup.send("That message has no text to translate.", ephemeral=True)
            return
        try:
            result = await self._translator().translate(text, to_lang="en")
        except Exception as exc:
            await interaction.followup.send(f"Translate failed: {exc}", ephemeral=True)
            return
        out = (result.get("text") if isinstance(result, dict) else str(result or "")).strip()
        detected = (result.get("lang") if isinstance(result, dict) else None) or "Unknown"
        if not out:
            await interaction.followup.send("Empty translation.", ephemeral=True)
            return
        from_name = _lang_display(detected)
        view = _translate_layout(
            original=text,
            translated=out,
            from_label=from_name,
            to_label="English",
            source_code=_lang_code(detected, "auto"),
            target_code="en",
        )
        await interaction.followup.send(view=view)

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
            text = await self._transcribe_bytes(
                audio, mime_type=voice.content_type or "audio/ogg"
            )
        except Exception as exc:
            await interaction.followup.send(f"Transcribe failed: {exc}", ephemeral=True)
            return
        embed = _transcribe_embed(text)
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
        if _is_gif(data, filename):
            await interaction.followup.send(
                "you **can't** OCR a **gif**\n> -# try using an **image** instead of a gif",
                ephemeral=True,
            )
            return
        try:
            text = await ocr_net.ocr_image(data, filename=filename)
        except Exception as exc:
            await interaction.followup.send(f"OCR failed: {exc}", ephemeral=True)
            return
        embed = _ocr_embed(text)
        await interaction.followup.send(embed=embed)

    @hybrid(
        name="ask",
        aliases=["chatgpt", "gemini", "gpt", "ai"],
        description="ask a question and get results from ai",
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
        pages = _ask_pages(answer)
        return await send_pages(ctx, pages)

    @hybrid(
        name="translate",
        aliases=["tr"],
        description="translate text using google translate",
        example=",tr es hello",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(
        text="Text to translate",
        to="Target language",
        source="Source language (auto-detects by default)",
    )
    @app_commands.rename(source="from")
    async def translate(
        self,
        ctx: Context,
        text: str,
        to: str = None,
        source: str = None,
    ) -> None:
        to_lang = (to or "en").strip().lower() if to else "en"
        from_lang = (source or "").strip().lower() or None
        if from_lang in {"auto", "detect", "none"}:
            from_lang = None
        body_text = (text or "").strip() or None  

        
        
        if body_text and not to and not source:
            tokens = body_text.split()
            if tokens and _LANG.match(tokens[0]):
                if len(tokens) >= 2 and _LANG.match(tokens[1]):
                    from_lang = tokens[0].lower()
                    to_lang = tokens[1].lower()
                    body_text = " ".join(tokens[2:]).strip() or None
                else:
                    to_lang = tokens[0].lower()
                    body_text = " ".join(tokens[1:]).strip() or None

        if body_text is None:
            if ctx.message and ctx.message.reference:
                ref = ctx.message.reference.resolved
                if not isinstance(ref, discord.Message):
                    try:
                        ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    except Exception:
                        ref = None
                if isinstance(ref, discord.Message) and (ref.content or "").strip():
                    body_text = ref.content.strip()

        if not body_text:
            return await ctx.warn(
                f"Provide text or reply to a message\n"
                f"> -# **usage:** {ctx.cmd('translate <from> <to> <text>')} or {ctx.cmd('tr <to> hello')}"
            )

        text = body_text

        async with ctx.typing():
            try:
                result = await self._translator().translate(text, to_lang=to_lang, from_lang=from_lang)
            except Exception as exc:
                return await ctx.fail(f"Translate failed\n> -# {exc}")

        out = (result.get("text") if isinstance(result, dict) else str(result or "")).strip()
        detected = (result.get("lang") if isinstance(result, dict) else None) or from_lang or "Unknown"
        if not out:
            return await ctx.warn("Empty translation")

        to_name = _lang_display(to_lang or "en")
        from_name = _lang_display(from_lang or detected)
        source_code = _lang_code(from_lang or detected, "auto")
        target_code = _lang_code(to_lang or "en", "en")
        view = _translate_layout(
            original=text,
            translated=out,
            from_label=from_name,
            to_label=to_name,
            source_code=source_code,
            target_code=target_code,
        )
        return await ctx.send(view=view)

    @translate.autocomplete("to")
    async def translate_to_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return _lang_autocomplete_choices(current, include_auto=False)

    @translate.autocomplete("source")
    async def translate_from_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return _lang_autocomplete_choices(current, include_auto=True)

    @commands.command(
        name="transcribe",
        aliases=["ts", "transcript"],
        description="transcribe a discord voice message",
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
                text = await self._transcribe_bytes(
                    audio, mime_type=voice.content_type or "audio/ogg"
                )
            except Exception as exc:
                return await ctx.fail(f"Transcribe failed\n> -# {exc}")

        embed = _transcribe_embed(text)
        try:
            return await ctx.reply(embed=embed, mention_author=False)
        except Exception:
            return await ctx.send(embed=embed)

    @hybrid(
        name="ocr",
        aliases=["extracttext", "readimage"],
        description="extract text from an image (ocr)",
        example=",ocr",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(attachment="Image to extract text from", url="Image URL")
    async def ocr(
        self,
        ctx: Context,
        attachment: discord.Attachment = None,
        url: str = None,
    ) -> None:
        data = None
        filename = "image.png"
        slash = bool(getattr(ctx, "interaction", None))

        if attachment is not None:
            try:
                data = await attachment.read()
                filename = attachment.filename or filename
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

        if _is_gif(data, filename):
            return await ctx.warn("you **can't** OCR a **gif**\n> -# try using an **image** instead of a gif")

        async with ctx.typing():
            try:
                text = await ocr_net.ocr_image(data, filename=filename)
            except Exception as exc:
                return await ctx.fail(f"OCR failed\n> -# {exc}")

        embed = _ocr_embed(text)
        return await ctx.send(embed=embed)


    @command(
        name="embedbuilder",
        aliases=["eb"],
        description="interactive embed builder with live preview. approve dms the script",
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

    @command(
        name="containerbuilder",
        aliases=["cb"],
        description="interactive components v2 container builder with live preview. approve dms the script",
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



    @command(
        name="dominant",
        aliases=["dom", "domcolor", "palette"],
        description="get dominant color(s) from avatars, image urls, or attachments",
        example=",dominant @user --colors 3",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    async def dominant(self, ctx: Context, *, query: str = None) -> None:
        """Extract dominant colors via ColorThief. Flag: --colors / --colour (1-5, default 1)."""
        import re as _re

        rest = (query or "").strip()
        if not rest and ctx.message and ctx.message.content:
            inv = ctx.invoked_with or "dominant"
            full = ctx.message.content
            idx = full.lower().find(inv.lower())
            if idx >= 0:
                rest = full[idx + len(inv) :].strip()

        color_count = 1
        tokens = rest.split() if rest else []
        cleaned_tokens: list[str] = []
        i = 0
        while i < len(tokens):
            low = tokens[i].lower().strip(",")
            if low in ("--colors", "--colour", "--color", "-c"):
                if i + 1 < len(tokens) and tokens[i + 1].lstrip(",").isdigit():
                    color_count = max(1, min(5, int(tokens[i + 1].strip(","))))
                    i += 2
                    continue
                i += 1
                continue
            if low.startswith("--colors=") or low.startswith("--colour=") or low.startswith("--color="):
                try:
                    color_count = max(1, min(5, int(low.split("=", 1)[1])))
                except Exception:
                    pass
                i += 1
                continue
            cleaned_tokens.append(tokens[i])
            i += 1
        rest = " ".join(cleaned_tokens).strip()

        sources: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        def _add(kind: str, url: str) -> None:
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            sources.append((kind, url))

        if ctx.message and ctx.message.attachments:
            atts = [
                a
                for a in ctx.message.attachments
                if (a.content_type or "").lower().startswith("image")
                or (a.filename or "").lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
                )
            ]
            for n, att in enumerate(atts, 1):
                media_url = getattr(att, "url", None) or getattr(att, "proxy_url", None)
                if not media_url:
                    continue
                label = "this attachment" if len(atts) == 1 else f"attachment #{n}"
                _add(label, str(media_url))

        mention_ids: set[int] = set()
        if ctx.message and ctx.message.mentions:
            for m in ctx.message.mentions:
                if m.bot and m.id == getattr(self.bot.user, "id", None):
                    continue
                mention_ids.add(m.id)
                _add(f"avatar:{m.id}", str(m.display_avatar.url))

        url_re = _re.compile(r"https?://\S+", _re.I)
        mention_re = _re.compile(r"<@!?(\d{15,25})>")
        id_re = _re.compile(r"^\d{15,25}$")

        
        for mid in mention_re.findall(rest or ""):
            try:
                uid = int(mid)
            except Exception:
                continue
            if uid in mention_ids:
                continue
            user = self.bot.get_user(uid)
            if user is None and ctx.guild is not None:
                user = ctx.guild.get_member(uid)
            if user is None:
                with contextlib.suppress(Exception):
                    user = await self.bot.fetch_user(uid)
            if user is None:
                continue
            mention_ids.add(uid)
            _add(f"avatar:{uid}", str(user.display_avatar.url))

        
        text = mention_re.sub(" ", rest or "")
        parts = [p.strip(" ,") for p in _re.split(r"[,\s]+", text) if p.strip(" ,")]

        for part in parts:
            m = url_re.search(part)
            if m:
                url = m.group(0).rstrip(")>.,'\"")
                _add("url", url)
                continue

            if id_re.match(part):
                uid = int(part)
                if uid in mention_ids:
                    continue
                user = self.bot.get_user(uid)
                if user is None and ctx.guild is not None:
                    user = ctx.guild.get_member(uid)
                if user is None:
                    with contextlib.suppress(Exception):
                        user = await self.bot.fetch_user(uid)
                if user is None:
                    continue
                mention_ids.add(uid)
                _add(f"avatar:{uid}", str(user.display_avatar.url))
                continue

            
            user = None
            if ctx.guild is not None:
                low = part.lower().lstrip("@")
                for member in ctx.guild.members:
                    if (
                        member.name.lower() == low
                        or member.display_name.lower() == low
                        or str(member).lower() == low
                        or (member.global_name and member.global_name.lower() == low)
                    ):
                        user = member
                        break
            if user is None:
                try:
                    user = await commands.MemberConverter().convert(ctx, part)
                except Exception:
                    try:
                        user = await commands.UserConverter().convert(ctx, part)
                    except Exception:
                        user = None
            if user is not None:
                if user.id in mention_ids:
                    continue
                mention_ids.add(user.id)
                _add(f"avatar:{user.id}", str(user.display_avatar.url))

        if not sources:
            if rest:
                return await ctx.warn(
                    "Attachments or URLs **must** be **GIFs** or **Images**"
                )
            _add(f"avatar:{ctx.author.id}", str(ctx.author.display_avatar.url))

        sources = sources[:10]

        async def _fetch_colors(url: str) -> list[str]:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status != 200:
                            return []
                        data = await resp.read()
            except Exception:
                return []

            def _extract() -> list[str]:
                try:
                    img = Image.open(BytesIO(data))
                    if getattr(img, "is_animated", False):
                        img.seek(0)
                    img = img.convert("RGB")
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    buf.seek(0)
                    ct = ColorThief(buf)
                    if color_count <= 1:
                        r, g, b = ct.get_color(quality=1)
                        return [f"#{r:02x}{g:02x}{b:02x}"]
                    palette = ct.get_palette(color_count=color_count, quality=1) or []
                    out = []
                    for rgb in palette[:color_count]:
                        r, g, b = rgb
                        out.append(f"#{r:02x}{g:02x}{b:02x}")
                    return out
                except Exception:
                    return []

            return await asyncio.to_thread(_extract)

        blocks: list[str] = []
        any_ok = False
        for idx, (kind, url) in enumerate(sources, 1):
            colors = await _fetch_colors(url)
            if not colors:
                continue
            any_ok = True
            if kind.startswith("avatar:"):
                uid = kind.split(":", 1)[1]
                title = f"[**dominant colors for <@{uid}>'s avatar**]({url})"
            elif kind == "url":
                if sum(1 for k, _ in sources if k == "url") == 1:
                    title = f"[**dominant colors for this url**]({url})"
                else:
                    url_n = sum(1 for k, _ in sources[:idx] if k == "url")
                    title = f"[**dominant colors for URL #{url_n}**]({url})"
            elif kind == "this attachment":
                title = f"[**dominant colors for this attachment**]({url})"
            else:
                title = f"[**dominant colors for {kind}**]({url})"
            color_bits = " ".join(f"`{c}`" for c in colors)
            blocks.append(f"-# {title}:\n{color_bits}")

        if not any_ok:
            return await ctx.warn(
                "Attachments or URLs **must** be **GIFs** or **Images**"
            )

        from discord import ui as _ui
        from core.discord.ctx import layout_from_items

        container = _ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                try:
                    setattr(container, attr, None)
                except Exception:
                    pass
        container.add_item(_ui.TextDisplay("\n\n".join(blocks)))
        view = layout_from_items([container], timeout=None)
        await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    from .events import SnipeEvents

    await bot.add_cog(Snipe(bot))
    await bot.add_cog(Utility(bot))

    if bot.get_cog("SnipeEvents") is None:
        await bot.add_cog(SnipeEvents(bot))
