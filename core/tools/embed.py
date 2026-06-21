"""embed builder and script parser.
converts tagscript style strings into discord embeds.
use Script for validation or PreparedScript for reusable payloads"""

from __future__ import annotations

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
    """Compatibility wrapper for callers that expect bored-style parsed scripts."""

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


def is_embed_script(raw: str) -> bool:
    """Return True when a template should be parsed as bleed embed code."""
    stripped = str(raw).strip()
    if (
        stripped.startswith("{embed}")
        or stripped.startswith("$v{")
        or stripped.lower().startswith("embed$v")
    ):
        return True
    lowered = stripped.lower()
    _EMBED_KEYS = (
        "content:", "description:", "title:", "color:", "field:",
        "footer:", "author:", "image:", "thumbnail:", "button:",
        "url:", "autodelete:", "timestamp",
    )
    if stripped.startswith("{") and any(lowered.startswith(f"{{{k}") for k in _EMBED_KEYS):
        return True
    return False


def maybe_wrap_embed_script(text: str) -> str:
    """Wrap plain text as ``{content: text}`` when it is not already embed code."""
    if is_embed_script(text):
        return text
    stripped = text.strip()
    if "{" in stripped and "}" in stripped:
        return text
    return f"{{content: {stripped}}}"


def _over_by(val, limit: int) -> int:
    return limit - (val if isinstance(val, int) else len(val))


def _split_fields(value: str) -> list[str]:
    return [part.strip() for part in str(value).split("&&")]


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "yes", "on", "1", "inline"}


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
    if lowered == "link":
        return discord.ButtonStyle.link
    if lowered == "blurple":
        return discord.ButtonStyle.primary
    if lowered == "green":
        return discord.ButtonStyle.success
    if lowered in {"grey", "gray"}:
        return discord.ButtonStyle.secondary
    if lowered == "red":
        return discord.ButtonStyle.danger
    return discord.ButtonStyle.secondary


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


class PassiveButton(discord.ui.Button):
    """Static button used by embed scripts for non-link button rows."""

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()


def _asset_url(asset) -> str:
    return asset.url if asset else ""


def _format_dt(value) -> str:
    if not value:
        return "Never"
    return value.strftime("%m/%d/%Y, %I:%M %p")


def _format_unix(value) -> str:
    if not value:
        return "Never"
    return str(int(value.timestamp()))


def _user_replacements(prefix: str, user) -> dict[str, str]:
    replacements = {
        f"{{{prefix}}}": str(user),
        f"{{{prefix}.id}}": str(user.id),
        f"{{{prefix}.mention}}": str(getattr(user, "mention", user)),
        f"{{{prefix}.name}}": str(getattr(user, "name", user)),
        f"{{{prefix}.bot}}": "Yes" if getattr(user, "bot", False) else "No",
        f"{{{prefix}.color}}": str(getattr(user, "color", "")),
        f"{{{prefix}.avatar}}": _asset_url(getattr(user, "display_avatar", None)),
        f"{{{prefix}.nickname}}": str(getattr(user, "display_name", user)),
        f"{{{prefix}.nick}}": str(getattr(user, "display_name", user)),
        f"{{{prefix}.created_at}}": _format_dt(getattr(user, "created_at", None)),
        f"{{unix({prefix}.created_at)}}": _format_unix(
            getattr(user, "created_at", None)
        ),
    }

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
        lowered = k.lower()
        if lowered in ("image", "thumbnail"):
            if v in ("", None, "None", "none"):
                data.pop(k)
            elif not _has_link(v.get("url", "")):
                raise BadEmbed(f"embed {lowered} url isnt valid `{v.get('url')}`")
        if lowered == "url" and not _has_link(v):
            raise BadEmbed("embed url isnt valid")
        if lowered == "title" and len(v) >= 256:
            raise BadEmbed(f"title too long ({_over_by(v, 256)} chars over)")
        if lowered == "description" and len(v) >= 4096:
            raise BadEmbed(f"description too long ({_over_by(v, 4096)} chars over)")
        if lowered == "fields":
            for index, field in enumerate(v):
                if len(field["name"]) >= 256:
                    raise BadEmbed(f"field {index + 1} name too long")
                if len(field["value"]) >= 1024:
                    raise BadEmbed(f"field {index + 1} value too long")
        if lowered == "footer" and len(v.get("text", "")) >= 2048:
            raise BadEmbed("footer too long")
    if len(discord.Embed.from_dict(data)) >= 6000:
        raise BadEmbed("embed total too long")
    return True


async def parse(raw: str, sendable: bool = False) -> dict:
    """parse embed script string into dict or embed"""
    raw = str(raw).strip().replace("{embed}", "")
    out: dict[str, Any] = {"fields": []}
    final: dict[str, Any] = {"view": discord.ui.View(timeout=None)}

    if raw.startswith("$v"):
        raw = raw[2:]
    if raw.endswith("$v"):
        raw = raw[:-2]

    chunks = [chunk.strip() for chunk in raw.split("$v") if chunk.strip()]
    if not chunks:
        return {}

    author_name = None
    author_icon = None
    author_url = None

    for chunk in chunks:
        if "}{" in chunk:
            raise ParseError("missing $v between }{")
        if not chunk.startswith("{"):
            raise ParseError(f"missing open brace in: {chunk}")
        if not chunk.endswith("}"):
            raise ParseError(f"missing close brace in: {chunk}")

    for chunk in chunks:
        part = Str(chunk)
        key = part.declaration
        if part.payload is None:
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
            bits = _split_fields(payload)
            out["footer"] = {"text": bits[0] if bits else ""}
            if len(bits) > 1 and bits[1]:
                if not _has_link(bits[1]):
                    raise BadEmbed("footer icon url invalid")
                out["footer"]["icon_url"] = bits[1]
            continue

        if lowered == "field":
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
            bits = _split_fields(payload)
            if len(bits) < 2:
                raise BadEmbed("button needs at least two arguments")

            first = bits[0]
            second = bits[1]
            third = bits[2] if len(bits) > 2 else ""
            fourth = bits[3] if len(bits) > 3 else None

            first_url = first if _has_link(first) else None
            label = second or None
            emoji = None
            url = None
            disabled = False

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
                if len(bits) < 3:
                    raise BadEmbed("styled buttons need a type, label, and emoji or url")
                style = _parse_button_style(first)
                target = third
                state = _parse_button_state(fourth)
                if state is None:
                    state = _parse_button_state(target)
                    if state is not None:
                        target = ""
                disabled = bool(state)

                if style == discord.ButtonStyle.link:
                    if not target or not _has_link(target):
                        raise BadEmbed("link buttons need a valid url")
                    url = target
                else:
                    emoji = _parse_button_emoji(target)

            if style == discord.ButtonStyle.link:
                final["view"].add_item(
                    discord.ui.Button(
                        label=label,
                        style=style,
                        url=url,
                        emoji=emoji,
                        disabled=disabled,
                    )
                )
            else:
                final["view"].add_item(
                    PassiveButton(
                        label=label,
                        style=style,
                        emoji=emoji,
                        disabled=disabled,
                    )
                )
            continue

        out[key] = payload

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

    if out:
        await _validate(out)

    if out:
        final["embed"] = out

    if sendable and final.get("embed"):
        final["embed"] = discord.Embed.from_dict(final["embed"])

    if not final["view"].children:
        final.pop("view", None)

    return final


async def parse_embed_script(raw: str, _ctx: Context | None = None) -> ParsedEmbedScript:
    """Return a compatibility object for embed-script consumers."""
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


class PreparedScript:
    """prepared embed payload returned by bot.create_embed."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    async def send(self, destination, **kwargs) -> discord.Message:
        payload = {**self.data, **kwargs}
        if isinstance(destination, discord.Message):
            payload.pop("delete_after", None)
            return await destination.edit(**payload)
        return await destination.send(**payload)


class Script:
    """shared bleed embed/template builder."""

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
        guild = kwargs.get("guild") or getattr(user, "guild", None)
        channel = kwargs.get("channel")
        role = kwargs.get("role")
        roles = kwargs.get("roles")

        if user:
            replacements.update(_user_replacements("user", user))

        if moderator:
            replacements.update(_user_replacements("moderator", moderator))

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

        return replacements

    def render(self, **kwargs) -> str:
        content = (
            self.template.replace("`​`​`", "```")
            .replace(r"\n", "\n")
            .replace("\\n", "\n")
            .replace("{member.", "{user.")
            .replace("{member}", "{user}")
        )
        for key, value in self._replacements(**kwargs).items():
            content = content.replace(key, value)
        return content

    async def data(self, sendable: bool = False, **kwargs) -> dict[str, Any]:
        rendered = self.render(**kwargs)
        rendered = maybe_wrap_embed_script(rendered)
        if is_embed_script(rendered):
            payload = await parse(rendered, sendable=sendable)
        else:
            payload = {"content": rendered}
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
        if isinstance(destination, discord.Message):
            payload.pop("delete_after", None)
            return await destination.edit(**payload)
        return await destination.send(**payload)

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
