"""embed builder and script parser.
converts tagscript style strings into discord embeds.
use Script for validation or PreparedScript for reusable payloads"""

from __future__ import annotations

import contextlib
import datetime
import re
from typing import Any, Optional, Union

import aiohttp
import discord
from discord import TextChannel, Thread
from discord.ext.commands import Context
from TagScriptEngine import Verb as Str

from core.tools.models import ScriptType

_URL_RE = re.compile(r"^(https?://)([a-zA-Z0-9.-]+)(\.[a-zA-Z]{2,})(/.*)?$")
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class ParseError(Exception):
    """bad embed script format"""

    def __init__(self, msg: str):
        self.message = msg
        super().__init__(msg)


class BadEmbed(Exception):
    """invalid embed content"""

    def __init__(self, msg: str):
        self.message = msg
        super().__init__(msg)


class ParsedEmbedScript:
    """Compatibility wrapper for callers that expect vain-style parsed scripts."""

    def __init__(
        self,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        embeds: list[discord.Embed] | None = None,
        view: discord.ui.View | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
        delete_after: float | int | None = None,
    ) -> None:
        self.content = content
        self.embed = embed
        self.embeds = embeds or []
        self.view = view
        self.allowed_mentions = allowed_mentions
        self.delete_after = delete_after

    def has_message(self) -> bool:
        return any(
            (
                self.content,
                self.embed is not None,
                bool(self.embeds),
                self.view is not None,
            )
        )

    def to_send_kwargs(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.content is not None:
            payload["content"] = self.content
        if self.embed is not None:
            payload["embed"] = self.embed
        elif self.embeds:
            if len(self.embeds) == 1:
                payload["embed"] = self.embeds[0]
            else:
                payload["embeds"] = self.embeds
        if self.view is not None:
            payload["view"] = self.view
        if self.allowed_mentions is not None:
            payload["allowed_mentions"] = self.allowed_mentions
        if self.delete_after is not None:
            payload["delete_after"] = self.delete_after
        return payload


def _has_link(s: str) -> bool:
    pat = r"((https?://)([\w\-./])*(.[a-zA-Z]{2,3}/?))([^\s\b\n|]*)[^.,;:?!@^$ -]"
    return len(re.findall(pat, s)) > 0


_EMBED_FIELD_KEYS = (
    "content:",
    "message:",
    "description:",
    "title:",
    "color:",
    "field:",
    "footer:",
    "author:",
    "image:",
    "thumbnail:",
    "button:",
    "url:",
    "autodelete:",
    "timestamp",
    "divider",
    "separator",
    "text:",
)


_SMART_EMBED_HINTS = (
    "{title:",
    "{description:",
    "{color:",
    "{author:",
    "{author.name:",
    "{footer:",
    "{field:",
    "{image:",
    "{thumbnail:",
    "{url:",
    "{button:",
    "{content:",
    "{message:",
)


def is_container_script(raw: str) -> bool:
    """Return True when a template is Components V2 container script."""
    raw = _strip_code_fences(raw)
    stripped = str(raw).strip().lower()
    if stripped.startswith("{container}") or stripped.startswith("container$v"):
        return True
    if re.search(r"\{container\b", stripped):
        return True
    return False


def _strip_code_fences(text: str) -> str:
    """Strip outer code fences and matching quotes wrapping an embed/container script."""
    s = str(text or "").strip()
    if not s:
        return s

    openers = {
        '"': '"',
        "'": "'",
        "\u201c": "\u201d",
        "\u2018": "\u2019",
        "`": "`",
    }
    
    openers = {
        '"': '"',
        "'": "'",
        "“": "”",
        "‘": "’",
        "`": "`",
    }

    def _unwrap_once(val: str):
        v = val.strip()
        if not v:
            return None
        if v.startswith("```"):
            body = v[3:]
            nl = body.find(chr(10))
            if nl != -1:
                first, rest = body[:nl], body[nl + 1:]
                if first.strip() and " " not in first.strip() and "{" not in first and "$" not in first:
                    body = rest
                else:
                    body = first + chr(10) + rest
            body = body.rstrip()
            if body.endswith("```"):
                body = body[:-3].rstrip()
            return body.strip()
        first = v[0]
        if first in openers:
            close = openers[first]
            if len(v) >= 2 and v.endswith(close):
                inner = v[1:-1].strip()
                low = inner[:40].lower()
                if (
                    inner.startswith("{")
                    or inner.startswith("$v")
                    or low.startswith("embed")
                    or low.startswith("container")
                    or "$v{" in inner
                ):
                    return inner
        return None

    for _ in range(8):
        nxt = _unwrap_once(s)
        if nxt is None or nxt == s:
            break
        s = nxt

    return s.strip()


def is_embed_script(raw: str) -> bool:
    """Return True when a template should be parsed as vain embed code.

    Smart default: bare ``{title:}`` / ``{description:}`` (etc.) scripts without
    an explicit ``{embed}`` or ``{container}`` tag are treated as embeds.
    """
    raw = _strip_code_fences(raw)
    if is_container_script(raw):
        return False
    stripped = str(raw).strip()
    if (
        stripped.startswith("{embed}")
        or stripped.startswith("$v{")
        or stripped.lower().startswith("embed$v")
    ):
        return True
    lowered = stripped.lower()
    if stripped.startswith("{") and any(
        lowered.startswith(f"{{{k}") for k in _EMBED_FIELD_KEYS if k != "timestamp"
    ):
        return True
    
    if any(hint in lowered for hint in _SMART_EMBED_HINTS):
        return True
    if "$v{" in stripped and any(
        f"{{{k.rstrip(':')}" in lowered or f"{k}" in lowered for k in _EMBED_FIELD_KEYS
    ):
        return True
    return False


def _strip_subtext_prefix(text: str) -> str:
    """Remove leading ``-#`` markers so callers can re-apply a single one."""
    cleaned = str(text or "").strip()
    while cleaned.startswith("-#"):
        cleaned = cleaned[2:].lstrip()
    return cleaned


def _looks_like_json(text: str) -> bool:
    s = str(text or "").strip()
    return (s.startswith("{") and s.endswith("}")) or (
        s.startswith("[") and s.endswith("]")
    )


def _discohook_color(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("#"):
            return raw
        if raw.lower().startswith("0x"):
            try:
                return f"#{int(raw, 16):06x}"
            except ValueError:
                return None
        if raw.isdigit():
            try:
                return f"#{int(raw):06x}"
            except ValueError:
                return None
        return raw
    try:
        return f"#{int(value):06x}"
    except Exception:
        return None


def _discohook_embed_to_script(embed: dict) -> str:
    """Convert one discohook/discord embed object into vain ``{embed}$v…`` script."""
    parts = ["{embed}"]
    if embed.get("title"):
        parts.append(f"$v{{title: {embed['title']}}}")
    if embed.get("description"):
        parts.append(f"$v{{description: {embed['description']}}}")
    color = _discohook_color(embed.get("color"))
    if color:
        parts.append(f"$v{{color: {color}}}")
    if embed.get("url"):
        parts.append(f"$v{{url: {embed['url']}}}")
    author = embed.get("author") or {}
    if isinstance(author, dict) and author.get("name"):
        bits = [str(author["name"])]
        icon = author.get("icon_url") or author.get("iconUrl")
        url = author.get("url")
        if icon:
            bits.append(str(icon))
        elif url:
            bits.append("")
        if url:
            bits.append(str(url))
        parts.append(f"$v{{author: {' && '.join(bits)}}}")
    footer = embed.get("footer") or {}
    if isinstance(footer, dict) and footer.get("text"):
        fbits = [str(footer["text"])]
        ficon = footer.get("icon_url") or footer.get("iconUrl")
        if ficon:
            fbits.append(str(ficon))
        parts.append(f"$v{{footer: {' && '.join(fbits)}}}")
    if embed.get("timestamp"):
        parts.append("$v{timestamp}")
    image = embed.get("image") or {}
    if isinstance(image, dict) and image.get("url"):
        parts.append(f"$v{{image: {image['url']}}}")
    elif isinstance(image, str) and image:
        parts.append(f"$v{{image: {image}}}")
    thumb = embed.get("thumbnail") or {}
    if isinstance(thumb, dict) and thumb.get("url"):
        parts.append(f"$v{{thumbnail: {thumb['url']}}}")
    elif isinstance(thumb, str) and thumb:
        parts.append(f"$v{{thumbnail: {thumb}}}")
    for field in embed.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = field.get("name") or "Field"
        value = field.get("value") or "​"
        inline = field.get("inline")
        tail = " && inline" if inline in (True, "true", "yes", "1") else ""
        parts.append(f"$v{{field: {name} && {value}{tail}}}")
    return "".join(parts) if len(parts) > 1 else ""


def discohook_to_script(text: str) -> str | None:
    """Convert discohook / discord message JSON into vain script text.

    Supports shapes like:
      {"content":"hi","embeds":[{...}]}
      {"embeds":[{...}]}
      [{...embed...}]
      {...single embed...}
    Returns None when input is not JSON / not discohook-like.
    """
    import json

    raw = str(text or "").strip()
    if not raw or not _looks_like_json(raw):
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None

    content = None
    embeds: list[dict] = []

    if isinstance(data, list):
        embeds = [e for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        if "embeds" in data or "content" in data or "components" in data:
            content = data.get("content")
            embeds = [e for e in (data.get("embeds") or []) if isinstance(e, dict)]
        elif any(
            k in data
            for k in (
                "title",
                "description",
                "fields",
                "author",
                "footer",
                "image",
                "thumbnail",
                "color",
            )
        ):
            embeds = [data]
        else:
            return None
    else:
        return None

    
    if embeds:
        script = _discohook_embed_to_script(embeds[0])
        if content:
            
            if script.startswith("{embed}"):
                script = script.replace("{embed}", f"{{embed}}$v{{content: {content}}}", 1)
            else:
                script = f"{{embed}}$v{{content: {content}}}" + script
        return script or (str(content) if content else None)
    if content is not None:
        return str(content)
    return None


def maybe_wrap_embed_script(text: str) -> str:
    """Normalize scripts: auto-prefix ``{embed}`` when field tags are present.

    Rules:
    - discohook / discord message JSON → converted to ``{embed}$v…`` (or plain)
    - ``{container}`` / ``container$v`` → left alone (Components V2)
    - ``{embed}`` / ``embed$v`` / bare ``{title:}`` etc. → classic embed
    - plain text with no field tags → plain content message (no wrap)
    """
    stripped = _strip_code_fences(str(text).strip())
    if not stripped:
        return stripped

    converted = discohook_to_script(stripped)
    if converted is not None:
        return converted
    if is_container_script(stripped):
        return stripped
    if is_embed_script(stripped):
        lowered = stripped.lower()
        if (
            lowered.startswith("{embed}")
            or lowered.startswith("embed$v")
            or lowered.startswith("{container}")
            or lowered.startswith("container$v")
        ):
            return stripped
        if stripped.startswith("$v{"):
            return "{embed}" + stripped
        if stripped.startswith("{"):
            return f"{{embed}}$v{stripped}"

        return f"{{embed}}$v{stripped}" if "$v{" in stripped else stripped
    return stripped


_SELF_DESTRUCT_RE = re.compile(
    r"(?:--self[_-]?destruct|--delete[_-]?after)\s+(\d+)"
    r"(?:\s*((?:secs?|seconds?|mins?|minutes?|hrs?|hours?|days?|weeks?|[smhdw])))?\b",
    re.IGNORECASE,
)

_self_destruct_units = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}


def extract_self_destruct(raw: str) -> tuple[str, int | None]:
    """Strip ``--self_destruct <time>`` / ``--delete_after <time>`` tokens from a script.

    Accepts bare seconds (``10``) and durations with aliases, spaced or not:
    seconds (``10s``/``10sec``/``10 seconds``), minutes (``5m``/``5mins``/``5 mins``),
    hours (``1h``/``1hr``/``1 hour``), plus ``d``/``day(s)`` and ``w``/``week(s)``.
    A bare number always means seconds. Returns ``(cleaned_script, seconds_or_none)``
    so every script sender can apply ``delete_after`` centrally.
    """
    seconds: int | None = None

    def _replace(match: re.Match) -> str:
        nonlocal seconds
        amount = int(match.group(1))
        unit = (match.group(2) or "").lower()
        seconds = amount * _self_destruct_units.get(unit, 1)
        return ""

    cleaned = _SELF_DESTRUCT_RE.sub(_replace, str(raw))
    return cleaned, seconds


def parse_duration_token(token: str) -> int | None:
    """Parse a duration token into seconds.

    Accepts bare numbers (``10`` = seconds) and unit aliases, spaced or not:
    ``10s``/``10sec``/``10 seconds``, ``5m``/``5mins``/``5 mins``,
    ``1h``/``1hr``/``1 hour``, plus ``d``/``day(s)`` and ``w``/``week(s)``.
    Returns ``None`` when the token is not a valid duration.
    """
    match = re.fullmatch(
        r"(\d+)(?:\s*((?:secs?|seconds?|mins?|minutes?|hrs?|hours?|days?|weeks?|[smhdw])))?",
        str(token or "").strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    amount = int(match.group(1))
    unit = (match.group(2) or "").lower()
    return amount * _self_destruct_units.get(unit, 1)


def _over_by(val, limit: int) -> int:
    return limit - (val if isinstance(val, int) else len(val))


def _split_top_level(value: str, sep: str) -> list[str]:
    """Split on ``sep`` only at brace depth 0."""
    text = str(value or "")
    if not sep:
        return [text] if text else []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(sep)
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0 and text.startswith(sep, i):
            parts.append("".join(buf).strip())
            buf = []
            i += n
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p != ""]


def _split_fields(value: str) -> list[str]:
    """Split on top-level ``&&`` only (ignore && inside nested braces).

    Also accepts legacy ``|`` and ``;`` separators when no ``&&`` is present.
    """
    text = str(value or "")
    if "&&" in text:
        return _split_top_level(text, "&&")
    
    if "|" in text and "{" not in text:
        return [p.strip() for p in text.split("|") if p.strip()]
    if ";" in text and not re.search(r"https?://", text):
        return [p.strip() for p in text.split(";") if p.strip()]
    return _split_top_level(text, "&&")


def _split_script_chunks(raw: str) -> list[str]:
    """Split embed/container body on top-level ``$v`` separators."""
    return _split_top_level(raw, "$v")


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "yes", "on", "1", "inline"}


def _parse_named_pairs(payload: str) -> dict[str, str]:
    """Parse ``key: value && key: value`` pairs (nested braces preserved).

    Also accepts ``key=value`` and legacy ``key=value; key=value``.
    """
    out: dict[str, str] = {}
    
    text = str(payload or "")
    if ";" in text and "&&" not in text and re.search(r"[\w.]+\s*=", text):
        text = text.replace(";", "&&")
    for part in _split_fields(text):
        raw = part.strip()
        if not raw:
            continue
        
        m = re.match(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.*)$", raw, flags=re.S)
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            out[key] = val
            continue
        
        flag = raw.lower()
        if flag in {"inline", "timestamp", "divider"}:
            out[flag] = "true"
    return out


def _parse_button_state(value: str | None) -> bool | None:
    if not value:
        return None
    lowered = str(value).strip().lower()
    if lowered in {"enable", "enabled"}:
        return False
    if lowered in {"disable", "disabled"}:
        return True
    return None


def _parse_button_style(value: str) -> discord.ButtonStyle:
    lowered = str(value).strip().lower()
    if lowered in {"link", "url"}:
        return discord.ButtonStyle.link
    if lowered in {"blurple", "blue", "primary"}:
        return discord.ButtonStyle.primary
    if lowered in {"green", "success"}:
        return discord.ButtonStyle.success
    if lowered in {"grey", "gray", "secondary", "grayish"}:
        return discord.ButtonStyle.secondary
    if lowered in {"red", "danger", "yellow", "gold"}:
        
        return discord.ButtonStyle.danger
    return discord.ButtonStyle.secondary


def _style_name(style: discord.ButtonStyle) -> str:
    return {
        discord.ButtonStyle.link: "url",
        discord.ButtonStyle.primary: "blue",
        discord.ButtonStyle.success: "green",
        discord.ButtonStyle.secondary: "grey",
        discord.ButtonStyle.danger: "red",
    }.get(style, "grey")


def _parse_button_emoji(value: str | None) -> discord.PartialEmoji | None:
    if not value:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if cleaned.lower() in {"none", "null", "off"}:
        return None
    if cleaned.startswith("<:") or cleaned.startswith("<a:"):
        return discord.PartialEmoji.from_str(cleaned)
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError:
        return discord.PartialEmoji.from_str(cleaned)
    return None


def _parse_separator_spacing(value: str | int | None) -> Any:
    """Map spacing 1/2 (or small/large) to SeparatorSpacing when available."""
    raw = str(value if value is not None else "1").strip().lower()
    large = raw in {"2", "large", "big", "lg"}
    try:
        spacing_enum = getattr(discord, "SeparatorSpacing", None)
        if spacing_enum is not None:
            return spacing_enum.large if large else spacing_enum.small
    except Exception:
        pass
    return None


def _make_separator(*, visible: bool = True, spacing: str | int | None = 1):
    from discord import ui

    sp = _parse_separator_spacing(spacing)
    try:
        if sp is not None:
            return ui.Separator(visible=visible, spacing=sp)
        return ui.Separator(visible=visible)
    except TypeError:
        return ui.Separator(visible=visible)


def _unwrap_message_script(raw: str) -> str:
    """Normalize button message payloads that may be nested scripts."""
    text = str(raw or "").strip()
    if not text:
        return text
    
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()
    return text


class PassiveButton(discord.ui.Button):
    """Static button used by embed scripts for non-link button rows."""

    def __init__(self, *args: Any, message_script: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.message_script = (message_script or "").strip() or None

    async def callback(self, interaction: discord.Interaction) -> None:
        script = self.message_script
        if not script:
            if not interaction.response.is_done():
                await interaction.response.defer()
            return
        try:
            await _send_button_message(interaction, script)
        except Exception:
            if not interaction.response.is_done():
                with contextlib.suppress(Exception):
                    await interaction.response.send_message(
                        "Couldn't open that button message.",
                        ephemeral=True,
                    )


async def _send_button_message(interaction: discord.Interaction, script: str) -> None:
    """Reply ephemerally with plain text, embed, or container from a button script."""
    import contextlib

    raw = _unwrap_message_script(script)
    if not raw:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        return

    if is_container_script(raw) or is_embed_script(raw) or raw.startswith(("{", "$v")):
        try:
            payload = await parse(maybe_wrap_embed_script(raw), sendable=True)
        except Exception as exc:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Invalid button message: {exc}",
                    ephemeral=True,
                )
            return
        kwargs: dict[str, Any] = {}
        view = payload.get("view")
        if payload.get("embed") is not None:
            kwargs["embed"] = payload["embed"]
        if payload.get("embeds"):
            kwargs["embeds"] = payload["embeds"]
        if view is not None:
            kwargs["view"] = view
        
        if payload.get("content") is not None:
            kwargs["content"] = payload["content"]
        if not kwargs:
            kwargs["content"] = raw[:2000]
        if not interaction.response.is_done():
            await interaction.response.send_message(ephemeral=True, **kwargs)
        else:
            with contextlib.suppress(Exception):
                await interaction.followup.send(ephemeral=True, **kwargs)
        return

    
    if not interaction.response.is_done():
        await interaction.response.send_message(content=raw[:2000], ephemeral=True)
    else:
        with contextlib.suppress(Exception):
            await interaction.followup.send(content=raw[:2000], ephemeral=True)


def _parse_button_payload(payload: str) -> dict[str, Any]:
    """Parse button chunk supporting named and positional forms.

    Named (preferred)::
        label: qa && style: blue && message: {embed}$v{description: hi}
        label: site && style: url && url: https://example.com

    Positional (legacy)::
        blue && qa && ✨
        https://example.com && label
        primary && label && emoji
    """
    named = _parse_named_pairs(payload)
    result: dict[str, Any] = {
        "label": None,
        "style": discord.ButtonStyle.secondary,
        "url": None,
        "emoji": None,
        "disabled": False,
        "message": None,
    }

    if named and any(k in named for k in ("label", "style", "url", "message", "emoji")):
        label = named.get("label") or named.get("name") or "Button"
        style_raw = named.get("style") or named.get("type") or "grey"
        style = _parse_button_style(style_raw)
        url = (named.get("url") or named.get("link") or "").strip() or None
        
        emoji = None
        if "emoji" in named or "emote" in named:
            emoji = _parse_button_emoji(named.get("emoji") or named.get("emote"))
        message = named.get("message") or named.get("msg") or named.get("content")
        message = (message or "").strip() or None
        disabled = _parse_button_state(named.get("disabled") or named.get("state"))
        if style == discord.ButtonStyle.link or (url and _has_link(url or "")):
            style = discord.ButtonStyle.link
            if not url or not _has_link(url):
                raise BadEmbed("url buttons need a valid url")
        
        if style != discord.ButtonStyle.link and not message:
            if disabled is None:
                disabled = True
        result.update(
            {
                "label": label,
                "style": style,
                "url": url if style == discord.ButtonStyle.link else None,
                "emoji": emoji,
                "message": message,
                "disabled": bool(disabled) if disabled is not None else False,
            }
        )
        return result

    bits = _split_fields(payload)
    if len(bits) < 2:
        raise BadEmbed("button needs at least label + style/url")

    first, second = bits[0], bits[1]
    third = bits[2] if len(bits) > 2 else ""
    fourth = bits[3] if len(bits) > 3 else None

    first_url = first if _has_link(first) else None
    label = second or "Button"
    emoji = None
    url = None
    disabled = False
    message = None
    style = discord.ButtonStyle.secondary

    if first_url:
        style = discord.ButtonStyle.link
        url = first_url
        state_fourth = _parse_button_state(fourth)
        state_third = _parse_button_state(third)
        if state_fourth is not None:
            disabled = bool(state_fourth)
            emoji = _parse_button_emoji(third if state_third is None else "")
        elif state_third is not None:
            disabled = bool(state_third)
        else:
            emoji = _parse_button_emoji(third)
    else:
        style = _parse_button_style(first)
        
        for bit in bits[2:]:
            if is_embed_script(bit) or is_container_script(bit) or bit.startswith(("{embed}", "{container}")):
                message = bit
                break
        target = third
        state = _parse_button_state(fourth)
        if state is None:
            state = _parse_button_state(target)
            if state is not None:
                target = ""
        disabled = bool(state) if state is not None else False
        if style == discord.ButtonStyle.link:
            if not target or not _has_link(target):
                
                if _has_link(second):
                    url = second
                    label = first
                else:
                    raise BadEmbed("link buttons need a valid url")
            else:
                url = target
        else:
            if target and not message:
                emoji = _parse_button_emoji(target)

    result.update(
        {
            "label": label,
            "style": style,
            "url": url,
            "emoji": emoji,
            "disabled": disabled,
            "message": message,
        }
    )
    return result


def _build_button_from_payload(payload: str) -> discord.ui.Button:
    meta = _parse_button_payload(payload)
    label = meta.get("label") or "Button"
    style = meta.get("style") or discord.ButtonStyle.secondary
    url = meta.get("url")
    
    emoji = meta.get("emoji") or None
    disabled = bool(meta.get("disabled"))
    message = (meta.get("message") or "").strip() or None

    if style == discord.ButtonStyle.link:
        kwargs: dict[str, Any] = {
            "label": label,
            "style": style,
            "url": url,
            "disabled": disabled,
        }
        if emoji is not None:
            kwargs["emoji"] = emoji
        return discord.ui.Button(**kwargs)

    
    
    if not message:
        disabled = True

    kwargs = {
        "label": label,
        "style": style,
        "disabled": disabled,
        "message_script": message,
    }
    if emoji is not None:
        kwargs["emoji"] = emoji
    return PassiveButton(**kwargs)


def _asset_url(asset) -> str:
    return asset.url if asset else ""


def _format_dt(value) -> str:
    if not value:
        return "Never"
    try:
        from core.tools.human import human_date, parse_dt

        dt = parse_dt(value)
        if dt is not None:
            return human_date(dt)
    except Exception:
        pass
    if hasattr(value, "strftime"):
        return value.strftime("%m/%d/%Y, %I:%M %p")
    return str(value)


def _format_unix(value) -> str:
    if not value:
        return "Never"
    return str(int(value.timestamp()))


def _user_replacements(prefix: str, user) -> dict[str, str]:
    uid = getattr(user, "id", None)

    mention = f"<@{uid}>" if uid is not None else str(getattr(user, "mention", user))
    display = str(getattr(user, "display_name", None) or getattr(user, "name", user))
    replacements = {
        f"{{{prefix}}}": mention,
        f"{{{prefix}.id}}": str(uid or ""),
        f"{{{prefix}.userid}}": str(uid or ""),
        f"{{{prefix}.user_id}}": str(uid or ""),
        f"{{{prefix}.mention}}": mention,
        f"{{{prefix}.name}}": str(getattr(user, "name", user)),
        f"{{{prefix}.display}}": display,
        f"{{{prefix}.display_name}}": display,
        f"{{{prefix}.bot}}": "Yes" if getattr(user, "bot", False) else "No",
        f"{{{prefix}.color}}": str(getattr(user, "color", "")),
        f"{{{prefix}.avatar}}": _asset_url(getattr(user, "display_avatar", None)),
        f"{{{prefix}.nickname}}": display,
        f"{{{prefix}.nick}}": display,
        f"{{{prefix}.created_at}}": _format_dt(getattr(user, "created_at", None)),
        f"{{unix({prefix}.created_at)}}": _format_unix(
            getattr(user, "created_at", None)
        ),
    }

    top_role = getattr(user, "top_role", None)
    if top_role:
        replacements[f"{{{prefix}.top_role}}"] = str(top_role)
        replacements[f"{{{prefix}.top_role.mention}}"] = str(getattr(top_role, "mention", top_role))
        replacements[f"{{{prefix}.top_role.name}}"] = str(getattr(top_role, "name", top_role))

    member_roles = getattr(user, "roles", None)
    if member_roles:
        non_everyone = [r for r in member_roles if r.name != "@everyone"]
        replacements[f"{{{prefix}.roles}}"] = ", ".join(str(r) for r in non_everyone)
        replacements[f"{{{prefix}.role_count}}"] = str(len(non_everyone))

    joined_at = getattr(user, "joined_at", None)
    premium_since = getattr(user, "premium_since", None)
    if joined_at:
        replacements[f"{{{prefix}.joined_at}}"] = _format_dt(joined_at)
        replacements[f"{{unix({prefix}.joined_at)}}"] = _format_unix(joined_at)

    if hasattr(user, "premium_since"):
        replacements[f"{{{prefix}.boost}}"] = "Yes" if premium_since else "No"
        replacements[f"{{{prefix}.boosted_at}}"] = _format_dt(premium_since)
        replacements[f"{{unix({prefix}.boosted_at)}}"] = _format_unix(premium_since)
        replacements[f"{{{prefix}.boost_since}}"] = _format_dt(premium_since)
        replacements[f"{{unix({prefix}.boost_since)}}"] = _format_unix(premium_since)

    return replacements


async def _check_url(url: str) -> bool:
    """ping url and check mime type is image"""
    if not _URL_RE.match(url):
        return False
    async with aiohttp.ClientSession() as s:
        try:
            async with s.head(url) as r:
                return r.headers.get("Content-Type", "") in _ALLOWED_MIME
        except Exception:
            return False


async def _validate(data: dict) -> bool:
    """check embed dict fields are all valid"""
    for k, v in list(data.items()):
        lowered = str(k).lower()
        if lowered in ("image", "thumbnail"):
            if v in ("", None, "None", "none") or not isinstance(v, dict):
                data.pop(k)
            else:
                url = str(v.get("url") or "")
                if not _has_link(url):
                    raise BadEmbed(f"embed {lowered} url isnt valid `{url}`")
        elif lowered == "url":
            if not _has_link(str(v or "")):
                raise BadEmbed("embed url isnt valid")
        elif lowered == "title":
            if len(str(v or "")) >= 256:
                raise BadEmbed(f"title too long ({_over_by(str(v or ''), 256)} chars over)")
        elif lowered == "description":
            if len(str(v or "")) >= 4096:
                raise BadEmbed(
                    f"description too long ({_over_by(str(v or ''), 4096)} chars over)"
                )
        elif lowered == "fields":
            fields = v if isinstance(v, list) else []
            for index, field in enumerate(fields):
                if not isinstance(field, dict):
                    continue
                if len(str(field.get("name") or "")) >= 256:
                    raise BadEmbed(f"field {index + 1} name too long")
                if len(str(field.get("value") or "")) >= 1024:
                    raise BadEmbed(f"field {index + 1} value too long")
        elif lowered == "footer":
            text = ""
            if isinstance(v, dict):
                text = str(v.get("text") or "")
            if len(text) >= 2048:
                raise BadEmbed("footer too long")
    if len(discord.Embed.from_dict(data)) >= 6000:
        raise BadEmbed("embed total too long")
    return True


async def parse_container(raw: str, sendable: bool = False) -> dict:
    """Parse a ``{container}`` script into a LayoutView payload."""
    from discord import ui

    raw = str(raw).strip()
    
    raw = re.sub(r"^\s*\{container\}\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^\s*container\$v", "", raw, flags=re.IGNORECASE)

    if raw.startswith("$v"):
        raw = raw[2:]
    if raw.endswith("$v"):
        raw = raw[:-2]

    chunks = [chunk.strip() for chunk in _split_script_chunks(raw) if chunk.strip()]
    layout = ui.LayoutView(timeout=None)
    container = ui.Container()
    content: str | None = None
    accent: int | None = None
    lines: list[str] = []
    buttons: list[discord.ui.Button] = []
    delete_after = None

    def _flush_text() -> None:
        nonlocal lines
        if not lines:
            return
        body = "\n".join(lines)
        try:
            container.add_item(ui.TextDisplay(body))
        except Exception:
            pass
        lines = []

    for chunk in chunks:
        if not chunk.startswith("{") or not chunk.endswith("}"):
            continue
        part = Str(chunk)
        key = (part.declaration or "").lower()
        payload = (part.payload or "").strip() if part.payload is not None else ""

        if key in {"content", "message"}:
            if payload:
                content = payload
            continue
        if key == "autodelete":
            try:
                delete_after = int(payload)
            except ValueError as error:
                raise BadEmbed("autodelete must be a number") from error
            continue
        if key in {"divider", "separator"}:
            _flush_text()
            named = _parse_named_pairs(payload) if payload else {}
            
            
            
            
            visible = True
            if "divider" in named:
                visible = _parse_bool(named.get("divider") or "true")
            elif payload and payload.strip().lower() in {"false", "off", "0", "no", "hidden"}:
                visible = False
            spacing = named.get("spacing") or named.get("space") or "1"
            
            if not named and payload.strip() in {"1", "2"}:
                spacing = payload.strip()
            try:
                container.add_item(_make_separator(visible=visible, spacing=spacing))
            except Exception:
                pass
            continue
        if key == "section":
            
            named = _parse_named_pairs(payload) if payload else {}
            text = named.get("text") or named.get("description") or named.get("content") or payload
            thumb = named.get("thumbnail") or named.get("image") or named.get("icon") or ""
            _flush_text()
            if text and thumb and _has_link(thumb):
                try:
                    container.add_item(
                        ui.Section(
                            ui.TextDisplay(str(text)),
                            accessory=ui.Thumbnail(thumb),
                        )
                    )
                except Exception:
                    lines.append(str(text))
            elif text:
                lines.append(str(text))
            continue
        if key == "color":
            color_value = payload
            if not color_value.startswith("#"):
                try:
                    accent = discord.Color(value=int(color_value)).value
                    continue
                except Exception:
                    color_value = f"#{color_value}"
            try:
                accent = int(discord.Color.from_str(color_value))
            except Exception as error:
                raise BadEmbed(str(error)) from error
            continue
        if key == "title":
            lines.append(f"## {payload}" if payload else "")
            continue
        if key in {"description", "text"}:
            if payload:
                lines.append(payload)
            continue
        if key == "footer":
            named = _parse_named_pairs(payload)
            if named.get("text") or named.get("icon") or named.get("icon_url"):
                foot = _strip_subtext_prefix(named.get("text") or "")
            else:
                bits = _split_fields(payload)
                foot = _strip_subtext_prefix(bits[0]) if bits else ""
            if foot:
                lines.append(f"-# {foot}")
            continue
        if key == "author":
            named = _parse_named_pairs(payload)
            if named.get("name") or named.get("text"):
                name = named.get("name") or named.get("text") or ""
                icon = named.get("icon") or named.get("icon_url") or named.get("url") or ""
            else:
                bits = _split_fields(payload)
                name = bits[0] if bits else ""
                icon = bits[1] if len(bits) > 1 else ""
            if name and icon and _has_link(icon):
                _flush_text()
                try:
                    container.add_item(
                        ui.Section(
                            ui.TextDisplay(f"**{name}**"),
                            accessory=ui.Thumbnail(icon),
                        )
                    )
                except Exception:
                    lines.append(f"**{name}**")
            elif name:
                lines.append(f"**{name}**")
            continue
        if key == "field":
            named = _parse_named_pairs(payload)
            if named.get("name") and (named.get("value") or named.get("text")):
                lines.append(
                    f"**{named.get('name')}**\n{named.get('value') or named.get('text')}"
                )
            else:
                bits = _split_fields(payload)
                if len(bits) >= 2:
                    lines.append(f"**{bits[0]}**\n{bits[1]}")
            continue
        if key == "image":
            _flush_text()
            
            urls: list[str] = []
            for part in _split_fields(payload):
                
                named = _parse_named_pairs(part)
                candidate = (
                    named.get("url")
                    or named.get("image")
                    or named.get("src")
                    or part
                ).strip()
                if candidate and _has_link(candidate):
                    urls.append(candidate)
            urls = urls[:10]
            if urls:
                try:
                    gallery = ui.MediaGallery()
                    for u in urls:
                        gallery.add_item(media=u)
                    container.add_item(gallery)
                except Exception:
                    for u in urls:
                        lines.append(u)
            continue
        if key == "thumbnail":
            
            if payload and _has_link(payload):
                body = "\n".join(lines) if lines else "​"
                lines = []
                try:
                    container.add_item(
                        ui.Section(
                            ui.TextDisplay(body),
                            accessory=ui.Thumbnail(payload),
                        )
                    )
                except Exception:
                    lines.append(payload)
            elif payload:
                lines.append(payload)
            continue
        if key in {"actionrow", "action_row", "row"}:
            
            _flush_text()
            if buttons:
                try:
                    container.add_item(ui.Separator(visible=True))
                except Exception:
                    pass
                for i in range(0, len(buttons), 5):
                    row = ui.ActionRow(*buttons[i : i + 5])
                    container.add_item(row)
                buttons = []
            continue
        if key == "button":
            if len(buttons) >= 25:
                raise BadEmbed("max 25 buttons per message")
            try:
                buttons.append(_build_button_from_payload(payload))
            except BadEmbed:
                raise
            except Exception as error:
                raise BadEmbed(f"invalid button: {error}") from error
            continue

        if payload:
            lines.append(payload)

    _flush_text()

    if accent is not None:
        try:
            container.accent_color = accent
        except Exception:
            pass
    else:
        for _attr in ("accent_color", "accent_colour"):
            if hasattr(container, _attr):
                try:
                    setattr(container, _attr, None)
                except Exception:
                    pass

    if buttons:
        children = list(getattr(container, "children", []) or [])
        if not children or not isinstance(children[-1], ui.Separator):
            try:
                container.add_item(ui.Separator(visible=True))
            except Exception:
                pass
        for i in range(0, len(buttons), 5):
            try:
                row = ui.ActionRow(*buttons[i : i + 5])
                container.add_item(row)
            except Exception:
                
                for btn in buttons[i : i + 5]:
                    try:
                        container.add_item(ui.ActionRow(btn))
                    except Exception:
                        pass

    
    if not getattr(container, "children", None) and not lines:
        try:
            container.add_item(ui.TextDisplay("​"))
        except Exception:
            pass

    layout.add_item(container)
    final: dict[str, Any] = {"view": layout}
    
    if content is not None:
        final["content"] = content
    if delete_after is not None:
        final["delete_after"] = delete_after
    return final


async def parse(raw: str, sendable: bool = False) -> dict:
    """parse embed or container script string into dict or embed"""
    raw, self_destruct = extract_self_destruct(str(raw))
    raw_in = str(raw).strip()
    if is_container_script(raw_in):
        payload = await parse_container(raw_in, sendable=sendable)
        if self_destruct is not None:
            payload.setdefault("delete_after", self_destruct)
        return payload

    raw = raw_in
    
    raw = re.sub(r"^\s*\{embed\}\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^\s*embed\$v", "", raw, flags=re.IGNORECASE)
    out: dict[str, Any] = {"fields": []}
    final: dict[str, Any] = {"view": discord.ui.View(timeout=None)}

    if raw.startswith("$v"):
        raw = raw[2:]
    if raw.endswith("$v"):
        raw = raw[:-2]

    chunks = [chunk.strip() for chunk in _split_script_chunks(raw) if chunk.strip()]
    if not chunks:
        return {}

    author_name = None
    author_icon = None
    author_url = None

    for chunk in chunks:
        
        
        if not chunk.startswith("{"):
            raise ParseError(f"missing open brace in: {chunk}")
        if not chunk.endswith("}"):
            raise ParseError(f"missing close brace in: {chunk}")

    for chunk in chunks:
        part = Str(chunk)
        key = part.declaration or ""
        if part.payload is None:
            if key.lower() in {"timestamp", "unix"}:
                out["timestamp"] = (
                    datetime.datetime.now(datetime.timezone.utc).isoformat()
                )
                continue
            if self_destruct is not None:
                return {"content": key, "delete_after": self_destruct}
            return {"content": key}

        payload = part.payload.strip()
        lowered = key.lower()

        if lowered in {"content", "message"}:
            final["content"] = payload
            continue

        if lowered == "autodelete":
            try:
                final["delete_after"] = int(payload)
            except ValueError as error:
                raise BadEmbed("autodelete must be a number") from error
            continue

        if lowered == "timestamp":
            
            out["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            continue

        if lowered == "url":
            if not _has_link(payload):
                raise BadEmbed("embed url invalid")
            out["url"] = payload
            continue

        if lowered == "color":
            color_value = payload
            if not color_value.startswith("#"):
                try:
                    out["color"] = discord.Color(value=int(color_value)).value
                    continue
                except Exception:
                    color_value = f"#{color_value}"
            try:
                out["color"] = int(discord.Color.from_str(color_value))
            except Exception as error:
                raise BadEmbed(str(error)) from error
            continue

        if lowered in {"title", "description"}:
            out[lowered] = payload
            continue

        if lowered in {"image", "thumbnail"}:
            if not _has_link(payload):
                raise BadEmbed(f"{lowered} url invalid")
            out[lowered] = {"url": payload}
            continue

        if lowered == "author":
            named = _parse_named_pairs(payload)
            if named.get("name") or named.get("text"):
                name = named.get("name") or named.get("text") or ""
                icon = named.get("icon") or named.get("icon_url") or ""
                url = named.get("url") or named.get("link") or ""
            else:
                bits = _split_fields(payload)
                name = bits[0] if bits else ""
                icon = bits[1] if len(bits) > 1 else ""
                url = bits[2] if len(bits) > 2 else ""
            out["author"] = {"name": name}
            if icon:
                if not _has_link(icon):
                    raise BadEmbed("author icon url invalid")
                out["author"]["icon_url"] = icon
            if url:
                if not _has_link(url):
                    raise BadEmbed("author url invalid")
                out["author"]["url"] = url
            continue

        if lowered == "author.name":
            author_name = payload
            continue

        if lowered in {"author.icon", "author.icon_url"}:
            if payload and not _has_link(payload):
                raise BadEmbed("author icon url invalid")
            author_icon = payload
            continue

        if lowered == "author.url":
            if payload and not _has_link(payload):
                raise BadEmbed("author url invalid")
            author_url = payload
            continue

        if lowered == "footer":
            named = _parse_named_pairs(payload)
            if named.get("text") is not None or named.get("icon") or named.get("icon_url"):
                text = named.get("text") or ""
                icon = named.get("icon") or named.get("icon_url") or ""
            else:
                bits = _split_fields(payload)
                text = bits[0] if bits else ""
                icon = bits[1] if len(bits) > 1 else ""
            out["footer"] = {"text": text}
            if icon:
                if not _has_link(icon):
                    raise BadEmbed("footer icon url invalid")
                out["footer"]["icon_url"] = icon
            continue

        if lowered == "field":
            named = _parse_named_pairs(payload)
            if named.get("name") and (named.get("value") or named.get("text")):
                out["fields"].append(
                    {
                        "name": named.get("name") or "Field",
                        "value": named.get("value") or named.get("text") or "​",
                        "inline": _parse_bool(named.get("inline") or "false"),
                    }
                )
            else:
                bits = _split_fields(payload)
                if len(bits) < 2:
                    raise BadEmbed("field needs a name and value")
                out["fields"].append(
                    {
                        "name": bits[0],
                        "value": bits[1],
                        "inline": len(bits) > 2 and _parse_bool(bits[2]),
                    }
                )
            continue

        if lowered == "button":
            view = final.get("view")
            if isinstance(view, discord.ui.View):
                if len(view.children) >= 25:
                    raise BadEmbed("max 25 buttons per message")
                try:
                    view.add_item(_build_button_from_payload(payload))
                except BadEmbed:
                    raise
                except Exception as error:
                    raise BadEmbed(f"invalid button: {error}") from error
            continue

        out[str(key)] = payload

    if author_name or author_icon or author_url:
        out["author"] = {
            "name": author_name or "",
        }
        if author_icon:
            out["author"]["icon_url"] = author_icon
        if author_url:
            out["author"]["url"] = author_url

    if out.get("fields") == []:
        out.pop("fields")

    if out and "color" not in out:
        try:
            from config import color
            out["color"] = color.base
        except ImportError:
            out["color"] = 0xE1D2DE

    if out:
        await _validate(out)

    if out:
        final["embed"] = out

    if sendable and final.get("embed"):
        final["embed"] = discord.Embed.from_dict(final["embed"])

    if not final["view"].children:
        final.pop("view", None)

    if self_destruct is not None:
        final["delete_after"] = self_destruct
    return final


async def parse_embed_script(raw: str, _ctx: Context | None = None) -> ParsedEmbedScript:
    """Return a compatibility object for embed-script consumers."""
    raw = _strip_code_fences(raw)
    payload = await parse(raw, sendable=True)
    embed = payload.get("embed")
    embeds = payload.get("embeds") or []
    if embed is not None and not embeds:
        embeds = [embed]
    return ParsedEmbedScript(
        content=payload.get("content"),
        embed=embed,
        embeds=embeds,
        view=payload.get("view"),
        allowed_mentions=payload.get("allowed_mentions"),
        delete_after=payload.get("delete_after"),
    )


def to_code(
    embed: Union[dict, discord.Message, discord.Embed],
    message: Optional[str] = None,
) -> str:
    """convert embed object back to script string"""
    code = "{embed}"
    msg = None
    if isinstance(embed, dict):
        message = embed.pop("message", embed.pop("content", message))
        embed = discord.Embed.from_dict(embed)
    elif isinstance(embed, discord.Message):
        msg = embed
        message = message or str(embed.content)
        embed = embed.embeds[0]
    if msg:
        for component in msg.components:
            children = (
                [component]
                if isinstance(component, discord.Button)
                else getattr(component, "children", [])
            )
            for button in children:
                if isinstance(button, discord.Button) and button.url:
                    code += f"$v{{button: {button.label or ''} && {button.url}}}"
    if message:
        code += f"$v{{content: {message}}}"
    if embed.title:
        code += f"$v{{title: {embed.title}}}"
    if embed.description:
        code += f"$v{{description: {embed.description}}}"
    if embed.timestamp:
        code += "$v{timestamp: true}"
    if embed.url:
        code += f"$v{{url: {embed.url}}}"
    for field in embed.fields:
        inline = " && inline" if field.inline else ""
        code += f"$v{{field: {field.name} && {field.value}{inline}}}"
    if embed.footer:
        section = f"footer: {embed.footer.text}"
        if embed.footer.icon_url:
            section += f" && {embed.footer.icon_url}"
        code += f"$v{{{section}}}"
    if embed.author:
        section = f"author: {embed.author.name}"
        if embed.author.url:
            section += f" && {embed.author.url}"
        if embed.author.icon_url:
            section += f" && {embed.author.icon_url}"
        code += f"$v{{{section}}}"
    if embed.image.url:
        code += f"$v{{image: {embed.image.url}}}"
    if embed.thumbnail.url:
        code += f"$v{{thumbnail: {embed.thumbnail.url}}}"
    if embed.color:
        code += f"$v{{color: #{str(embed.color)}}}".replace("##", "#")
    return code.replace("```", "`​`​`")


def _is_layout_view(view: Any) -> bool:
    if view is None:
        return False
    try:
        return isinstance(view, discord.ui.LayoutView)
    except Exception:
        return type(view).__name__ == "LayoutView"


async def send_script_payload(
    destination,
    payload: dict[str, Any],
    **kwargs,
) -> discord.Message | None:
    """Send a parsed embed/container payload to ``destination``.

    Order:
    - plain text only -> one message
    - classic embed (+ optional content) -> one message
    - LayoutView/container + content -> content message first, container second
    - LayoutView only -> one message
    """
    merged = {**payload, **kwargs}
    if isinstance(destination, discord.Message):
        merged.pop("delete_after", None)
        merged.pop("raw_embed", None)
        return await destination.edit(**merged)

    content = merged.get("content")
    view = merged.get("view")
    if content and _is_layout_view(view):
        text = content if isinstance(content, str) else str(content)
        if text.strip():
            content_kw: dict[str, Any] = {}
            for key in (
                "tts",
                "nonce",
                "allowed_mentions",
                "reference",
                "mention_author",
                "silent",
                "stickers",
            ):
                if key in merged and merged[key] is not None:
                    content_kw[key] = merged[key]
            try:
                await destination.send(content=text, **content_kw)
            except Exception:
                pass
        merged["content"] = None
        merged.pop("reference", None)
        merged.pop("mention_author", None)
    return await destination.send(**merged)


class PreparedScript:
    """prepared embed payload returned by bot.create_embed."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    async def send(self, destination, **kwargs) -> discord.Message:
        payload = {**self.data, **kwargs}
        return await send_script_payload(destination, payload)


class Script:
    """shared vain embed/template builder."""

    def __init__(
        self,
        template: str | ScriptType,
        user: Optional[discord.abc.User] = None,
        lastfm: Optional[dict[str, Any]] = None,
    ):
        self.template = str(getattr(template, "script", template))
        self.user = user
        self.lastfm = lastfm or {}

    def _replacements(self, **kwargs) -> dict[str, str]:
        replacements = {"{whitespace}": "‎"}
        replacements.update(
            {str(key): str(value) for key, value in (kwargs.get("lastfm") or self.lastfm).items()}
        )

        user = kwargs.get("user") or kwargs.get("member") or self.user
        moderator = kwargs.get("moderator")
        inviter = kwargs.get("inviter")
        invitee = kwargs.get("invitee")
        guild = kwargs.get("guild") or getattr(user, "guild", None)
        channel = kwargs.get("channel")
        role = kwargs.get("role")
        roles = kwargs.get("roles")

        if user:
            replacements.update(_user_replacements("user", user))

        bumper = kwargs.get("bumper")
        if bumper:
            replacements.update(_user_replacements("bumper", bumper))
        elif user:
            
            replacements.update(_user_replacements("bumper", user))
        else:
            
            replacements.update(
                {
                    "{bumper}": "",
                    "{bumper.id}": "",
                    "{bumper.userid}": "",
                    "{bumper.user_id}": "",
                    "{bumper.mention}": "",
                    "{bumper.name}": "",
                    "{bumper.display}": "",
                    "{bumper.display_name}": "",
                    "{bumper.avatar}": "",
                    "{bumper.nickname}": "",
                    "{bumper.nick}": "",
                }
            )

        if moderator:
            replacements.update(_user_replacements("moderator", moderator))

        if inviter:
            replacements.update(_user_replacements("inviter", inviter))

        if invitee:
            replacements.update(_user_replacements("invitee", invitee))

        if guild:
            replacements.update(
                {
                    "{guild}": str(guild),
                    "{guild.id}": str(guild.id),
                    "{guild.name}": str(guild.name),
                    "{guild.icon}": _asset_url(guild.icon),
                    "{guild.banner}": _asset_url(getattr(guild, "banner", None)),
                    "{guild.splash}": _asset_url(getattr(guild, "splash", None)),
                    "{guild.discovery_splash}": _asset_url(
                        getattr(guild, "discovery_splash", None)
                    ),
                    "{guild.owner}": str(getattr(guild, "owner", "")),
                    "{guild.owner_id}": str(getattr(guild, "owner_id", "")),
                    "{guild.count}": str(getattr(guild, "member_count", 0)),
                    "{guild.members}": str(getattr(guild, "member_count", 0)),
                    "{guild.member_count}": str(getattr(guild, "member_count", 0)),
                    "{len(guild.members)}": str(getattr(guild, "member_count", 0)),
                    "{guild.channels}": str(len(getattr(guild, "channels", ()))),
                    "{guild.channel_count}": str(len(getattr(guild, "channels", ()))),
                    "{guild.category_channels}": str(
                        len(getattr(guild, "categories", ()))
                    ),
                    "{guild.category_channel_count}": str(
                        len(getattr(guild, "categories", ()))
                    ),
                    "{guild.text_channels}": str(
                        len(getattr(guild, "text_channels", ()))
                    ),
                    "{guild.text_channel_count}": str(
                        len(getattr(guild, "text_channels", ()))
                    ),
                    "{guild.voice_channels}": str(
                        len(getattr(guild, "voice_channels", ()))
                    ),
                    "{guild.voice_channel_count}": str(
                        len(getattr(guild, "voice_channels", ()))
                    ),
                    "{guild.roles}": str(len(getattr(guild, "roles", ()))),
                    "{guild.role_count}": str(len(getattr(guild, "roles", ()))),
                    "{guild.emojis}": str(len(getattr(guild, "emojis", ()))),
                    "{guild.emoji_count}": str(len(getattr(guild, "emojis", ()))),
                    "{guild.created_at}": _format_dt(getattr(guild, "created_at", None)),
                    "{unix(guild.created_at)}": _format_unix(
                        getattr(guild, "created_at", None)
                    ),
                    "{guild.boost_count}": str(
                        getattr(guild, "premium_subscription_count", 0)
                    ),
                    "{guild.boost_tier}": str(getattr(guild, "premium_tier", 0)),
                    "{guild.vanity}": str(
                        getattr(guild, "vanity_url_code", None) or ""
                    ),
                    "{guild.vanity_url}": (
                        f"https://discord.gg/{guild.vanity_url_code}"
                        if getattr(guild, "vanity_url_code", None)
                        else ""
                    ),
                }
            )

        now = datetime.datetime.now(datetime.timezone.utc)
        replacements.update(
            {
                "{date}": now.strftime("%Y-%m-%d"),
                "{time}": now.strftime("%H:%M:%S"),
                "{datetime}": now.strftime("%Y-%m-%d %H:%M:%S"),
                "{timestamp}": str(int(now.timestamp())),
                "{unix}": str(int(now.timestamp())),
            }
        )

        honeypot = kwargs.get("honeypot")
        if isinstance(honeypot, dict):
            try:
                caught = f"{int(honeypot.get('caught') or honeypot.get('caught_count') or 0):,}"
            except (TypeError, ValueError):
                caught = str(
                    honeypot.get("caught") or honeypot.get("caught_count") or 0
                )
            hp_channel = honeypot.get("channel")
            punishments = honeypot.get("punishments") or honeypot.get("punishment") or ""
            if isinstance(punishments, (list, tuple)):
                punishments = ", ".join(str(p) for p in punishments)
            ch_mention = ""
            ch_name = ""
            ch_id = ""
            if hp_channel is not None:
                ch_mention = str(getattr(hp_channel, "mention", hp_channel))
                ch_name = str(getattr(hp_channel, "name", hp_channel))
                ch_id = str(getattr(hp_channel, "id", hp_channel))
            else:
                ch_mention = str(honeypot.get("channel_mention") or "")
                ch_name = str(honeypot.get("channel_name") or "")
                ch_id = str(honeypot.get("channel_id") or "")
            replacements.update(
                {
                    "{honeypot.caught}": caught,
                    "{honeypot.caught_count}": caught,
                    "{honeypot.channel}": ch_mention,
                    "{honeypot.channel.name}": ch_name,
                    "{honeypot.channel.id}": ch_id,
                    "{honeypot.punishment}": str(punishments),
                    "{honeypot.punishments}": str(punishments),
                }
            )

        target = kwargs.get("target")
        if target:
            replacements.update(_user_replacements("target", target))

        reason = kwargs.get("reason")
        if reason is not None:
            replacements["{reason}"] = str(reason)

        duration = kwargs.get("duration")
        if duration is not None:
            replacements["{duration}"] = str(duration)

        action = kwargs.get("action")
        if action is not None:
            replacements["{action}"] = str(action)

        case_id = kwargs.get("case_id")
        if case_id is not None:
            replacements["{case_id}"] = str(case_id)

        invites = kwargs.get("invites")
        if invites is not None:
            replacements["{invites}"] = str(invites)

        invite_word = kwargs.get("invite_word")
        if invite_word is not None:
            replacements["{invite_word}"] = str(invite_word)

        code = kwargs.get("code")
        if code is not None:
            replacements["{code}"] = str(code)

        url = kwargs.get("url")
        if url is not None:
            replacements["{url}"] = str(url)

        invite = kwargs.get("invite")
        if invite:
            replacements.update(
                {
                    "{invite.code}": str(getattr(invite, "code", "")),
                    "{invite.inviter}": str(getattr(getattr(invite, "inviter", None), "name", "")),
                    "{invite.uses}": str(getattr(invite, "uses", 0)),
                    "{invite.url}": str(getattr(invite, "url", "")),
                    "{invite.max_uses}": str(getattr(invite, "max_uses", 0)),
                    "{invite.channel}": str(getattr(getattr(invite, "channel", None), "name", "")),
                }
            )

        if channel:
            replacements.update(
                {
                    "{channel}": str(channel),
                    "{channel.id}": str(channel.id),
                    "{channel.mention}": str(getattr(channel, "mention", channel)),
                    "{channel.name}": str(getattr(channel, "name", channel)),
                    "{channel.topic}": str(getattr(channel, "topic", "")),
                    "{channel.category}": str(getattr(getattr(channel, "category", None), "name", "")),
                    "{channel.created_at}": _format_dt(
                        getattr(channel, "created_at", None)
                    ),
                    "{unix(channel.created_at)}": _format_unix(
                        getattr(channel, "created_at", None)
                    ),
                }
            )

        if role:
            replacements.update(
                {
                    "{role}": str(role),
                    "{role.id}": str(role.id),
                    "{role.mention}": str(getattr(role, "mention", role)),
                    "{role.name}": str(getattr(role, "name", role)),
                    "{role.color}": str(getattr(role, "color", "")),
                    "{role.created_at}": _format_dt(getattr(role, "created_at", None)),
                    "{unix(role.created_at)}": _format_unix(
                        getattr(role, "created_at", None)
                    ),
                }
            )

        if roles:
            replacements["{roles}"] = " ".join(str(item) for item in roles)

        
        prize = kwargs.get("prize")
        if prize is not None:
            replacements["{prize}"] = str(prize)
            replacements["{giveaway.prize}"] = str(prize)

        winners = kwargs.get("winners")
        if winners is not None:
            if isinstance(winners, (list, tuple, set)):
                win_str = ", ".join(
                    getattr(w, "mention", str(w)) for w in winners
                )
            else:
                win_str = str(winners)
            replacements["{winners}"] = win_str
            replacements["{giveaway.winners}"] = win_str

        for gw_key, aliases in (
            ("winner_count", ("{winner_count}", "{giveaway.winner_count}")),
            ("host", ("{host}", "{giveaway.host}")),
            ("ends_at", ("{ends_at}", "{giveaway.ends_at}")),
            ("jump_url", ("{jump_url}", "{giveaway.url}", "{giveaway.jump_url}")),
            ("entries", ("{entries}", "{giveaway.entries}")),
        ):
            val = kwargs.get(gw_key)
            if val is not None:
                for alias in aliases:
                    replacements[alias] = str(val)

        
        vanity = kwargs.get("vanity") or kwargs.get("vanity_code")
        if vanity is None and guild is not None:
            vanity = getattr(guild, "vanity_url_code", None)
        if vanity is not None and str(vanity):
            code = str(vanity).lstrip("/")
            replacements["{vanity}"] = code
            replacements["{vanity.name}"] = code
            replacements["{vanity.code}"] = code
            replacements["{guild.vanity}"] = code
            replacements["{vanity.url}"] = f"https://discord.gg/{code}"

        
        vanity_role = kwargs.get("vanity_role")
        if vanity_role is not None:
            replacements["{vanity.role}"] = str(
                getattr(vanity_role, "mention", vanity_role)
            )
            replacements["{vanity.role.mention}"] = str(
                getattr(vanity_role, "mention", vanity_role)
            )
            replacements["{vanity.role.name}"] = str(
                getattr(vanity_role, "name", vanity_role)
            )
            replacements["{vanity.role.id}"] = str(
                getattr(vanity_role, "id", "")
            )

        
        tag = kwargs.get("tag")
        if tag is None and user is not None:
            pg = getattr(user, "primary_guild", None)
            if pg is not None:
                tag = getattr(pg, "tag", None)
        if tag is not None and str(tag):
            replacements["{tag}"] = str(tag)
            replacements["{tag.name}"] = str(tag)

        
        tag_role = kwargs.get("tag_role")
        if tag_role is not None:
            replacements["{tag.role}"] = str(getattr(tag_role, "mention", tag_role))
            replacements["{tag.role.mention}"] = str(
                getattr(tag_role, "mention", tag_role)
            )
            replacements["{tag.role.name}"] = str(
                getattr(tag_role, "name", tag_role)
            )
            replacements["{tag.role.id}"] = str(getattr(tag_role, "id", ""))

        
        
        bump = kwargs.get("bump")
        if isinstance(bump, dict):
            b_role = bump.get("role")
            b_channel = bump.get("channel")
            if b_role is not None:
                replacements.setdefault(
                    "{bump.role}", str(getattr(b_role, "mention", b_role))
                )
                replacements.setdefault(
                    "{bump.role.mention}", str(getattr(b_role, "mention", b_role))
                )
                replacements.setdefault(
                    "{bump.role.name}", str(getattr(b_role, "name", b_role))
                )
                replacements.setdefault(
                    "{bump.role.id}", str(getattr(b_role, "id", ""))
                )
            if b_channel is not None:
                replacements.setdefault(
                    "{bump.channel}", str(getattr(b_channel, "mention", b_channel))
                )
                replacements.setdefault(
                    "{bump.channel.mention}",
                    str(getattr(b_channel, "mention", b_channel)),
                )
                replacements.setdefault(
                    "{bump.channel.name}", str(getattr(b_channel, "name", b_channel))
                )
                replacements.setdefault(
                    "{bump.channel.id}", str(getattr(b_channel, "id", ""))
                )
            for stamp_key, aliases in (
                ("next", ("{bump.next}", "{next_bump}", "{next_bump_at}")),
                ("last", ("{bump.last}", "{last_bump}", "{last_bump_at}")),
            ):
                stamp = bump.get(stamp_key)
                if stamp is not None:
                    unix = _format_unix(stamp) if not isinstance(stamp, (str, int)) else str(
                        int(stamp) if isinstance(stamp, (int, float)) else stamp
                    )
                else:
                    unix = ""
                for alias in aliases:
                    replacements.setdefault(alias, unix)

        for stamp_key, aliases in (
            ("next_bump_at", ("{next_bump_at}", "{next_bump}", "{bump.next}")),
            ("last_bump_at", ("{last_bump_at}", "{last_bump}", "{bump.last}")),
        ):
            stamp = kwargs.get(stamp_key)
            if stamp is None:
                if isinstance(bump, dict):
                    for alias in aliases:
                        replacements.setdefault(alias, "")
                continue
            try:
                unix = _format_unix(stamp)
            except Exception:
                unix = str(stamp)
            for alias in aliases:
                replacements.setdefault(alias, unix)

        _reserved = {
            "user", "member", "moderator", "inviter", "invitee", "guild",
            "channel", "role", "roles", "target", "reason", "duration",
            "action", "case_id", "invites", "invite_word", "code", "url",
            "invite", "lastfm", "prize", "winners", "winner_count", "host",
            "ends_at", "jump_url", "entries", "vanity", "vanity_code",
            "vanity_role", "tag", "tag_role", "allowed_mentions", "view",
            "file", "files", "embed", "embeds", "content", "delete_after",
            "silent", "ephemeral", "mention_author", "reference",
            "bumper", "bump", "honeypot", "next_bump_at", "last_bump_at",
        }
        for key, value in kwargs.items():
            if key in _reserved or value is None:
                continue
            if not isinstance(value, (str, int, float, bool)):
                continue
            token = key if str(key).startswith("{") else f"{{{key}}}"
            replacements.setdefault(token, str(value))

        return replacements

    def render(self, **kwargs) -> str:
        content = (
            self.template.replace("`​`​`", "```")
            .replace(r"\n", "\n")
            .replace("\\n", "\n")
            .replace("{member.", "{user.")
            .replace("{member}", "{user}")
        )
        
        protected: list[tuple[str, str]] = []
        for flag in ("$v{timestamp}", "$v{unix}"):
            if flag in content:
                marker = f"\x00proto{len(protected)}\x00"
                content = content.replace(flag, marker)
                protected.append((marker, flag))

        replacements = self._replacements(**kwargs)
        for key in sorted(replacements.keys(), key=len, reverse=True):
            content = content.replace(key, replacements[key])
        for marker, flag in protected:
            content = content.replace(marker, flag)
        return content

    async def data(self, sendable: bool = False, **kwargs) -> dict[str, Any]:
        rendered = self.render(**kwargs)
        rendered, self_destruct = extract_self_destruct(rendered)
        rendered = maybe_wrap_embed_script(rendered)
        if is_container_script(rendered) or is_embed_script(rendered):
            payload = await parse(rendered, sendable=sendable)
        else:
            payload = {"content": rendered}
        if self_destruct is not None:
            payload.setdefault("delete_after", self_destruct)
        for option in ("delete_after", "allowed_mentions", "reference", "ephemeral"):
            if option in kwargs and kwargs[option] is not None:
                payload[option] = kwargs[option]
        return payload

    async def send(
        self,
        destination: Union[TextChannel, Thread, discord.Message],
        **kwargs,
    ) -> discord.Message:
        payload = await self.data(True, **kwargs)
        
        if payload.get("embed") is not None and "raw_embed" not in payload:
            
            if hasattr(destination, "send"):
                try:
                    import inspect
                    sig = inspect.signature(destination.send)
                    if "raw_embed" in sig.parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    ):
                        payload.setdefault("raw_embed", True)
                except (TypeError, ValueError):
                    payload.setdefault("raw_embed", True)
        return await send_script_payload(destination, payload)

    async def compile(self, **kwargs) -> bool:
        await self.data(False, **kwargs)
        return True

    def replace(self, key: str, value: str) -> "Script":
        self.template = self.template.replace(key, value)
        return self

    def strip(self) -> "Script":
        self.template = self.template.strip()
        return self

    @classmethod
    async def convert(cls, ctx: Context, template: str) -> ScriptType:
        await cls(template, ctx.author).compile(user=ctx.author)
        return ScriptType(template)
