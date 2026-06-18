"""embed builder and script parser.
converts tagscript style strings into discord embeds.
use Script class or m() function directly"""

from __future__ import annotations
import asyncio, datetime, re
from typing import Any, Dict, Optional, Union
import aiohttp, discord
from discord import TextChannel, Thread
from discord.ext.commands import Context
import TagScriptEngine as tse
from TagScriptEngine import Verb as Str

_URL_RE = re.compile(
    r"^(https?://)([a-zA-Z0-9.-]+)(\.[a-zA-Z]{2,})(/.*)?$"
)
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


def _has_link(s: str) -> bool:
    pat = r"((https?://)([\w\-./])*(.[a-zA-Z]{2,3}/?))([^\s\b\n|]*)[^.,;:?!@^$ -]"
    return len(re.findall(pat, s)) > 0


def _over_by(val, limit: int) -> int:
    return limit - (val if isinstance(val, int) else len(val))


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
    for k, v in data.items():
        k = k.lower()
        if k in ("image", "thumbnail"):
            if v in ("", None, "None", "none"):
                data.pop(k)
            elif not _has_link(v.get("url", "")):
                raise BadEmbed(f"embed {k} url isnt valid `{v.get('url')}`")
        if k == "url" and not _has_link(v):
            raise BadEmbed("embed url isnt valid")
        if k == "title" and len(v) >= 256:
            raise BadEmbed(f"title too long ({_over_by(v, 256)} chars over)")
        if k == "description" and len(v) >= 4096:
            raise BadEmbed(f"description too long ({_over_by(v, 4096)} chars over)")
        if k == "fields":
            for i, f in enumerate(v):
                if len(f["name"]) >= 256:
                    raise BadEmbed(f"field {i+1} name too long")
                if len(f["value"]) >= 1024:
                    raise BadEmbed(f"field {i+1} value too long")
        if k == "footer" and len(v.get("text", "")) >= 2048:
            raise BadEmbed(f"footer too long")
    if len(discord.Embed.from_dict(data)) >= 6000:
        raise BadEmbed("embed total too long")
    return True


async def parse(raw: str, sendable: bool = False) -> dict:
    """parse embed script string into dict or embed"""
    raw = str(raw).replace("{embed}", "")
    out: dict = {"fields": []}
    final: dict = {"view": discord.ui.View()}

    if raw.startswith("$v"):
        raw = raw[2:]
    if raw.endswith("$v"):
        raw = raw[:-2]

    chunks = raw.split("$v")
    for chunk in chunks:
        if "}{" in chunk:
            raise ParseError("missing $v between }{")
        if not chunk.startswith("{"):
            raise ParseError(f"missing open brace in: {chunk}")
        if not chunk.endswith("}"):
            raise ParseError(f"missing close brace in: {chunk}")

    for chunk in chunks:
        part = Str(chunk)
        k = part.declaration
        if part.payload is None:
            return {"content": k}
        pay = part.payload.strip()

        if pay and " && " in pay:
            bits = pay.split(" && ")
            kl = k.lower()
            if kl == "footer":
                out["footer"] = {"text": bits[0], "icon": bits[1].replace("icon: ", "") if len(bits) > 1 else ""}
            elif kl == "field":
                field = {"name": bits[0], "value": bits[1].replace("value:", "")}
                if len(bits) == 3:
                    field["inline"] = bool(bits[2].replace("inline:", "").strip())
                out["fields"].append(field)
            elif kl in ("author", "uthor"):
                auth: dict = {"name": bits[0]}
                for bit in bits[1:]:
                    bit = bit.strip()
                    if "icon:" in bit:
                        icon = bit.replace("icon:", "")
                        if not _has_link(icon):
                            raise BadEmbed("author icon url invalid")
                        auth["icon_url"] = icon
                    elif ":" in bit:
                        url = bit.split(":", 1)[1]
                        if not _has_link(url):
                            raise BadEmbed("author url invalid")
                        auth["url"] = url
                out["author"] = auth
            elif kl == "label":
                final["view"].add_item(discord.ui.Button(label=bits[0], url=bits[1].strip("link:").strip()))
            else:
                obj: dict = {}
                for bit in bits:
                    if ":" in bit:
                        p = bit.split(":", 1)
                        obj[p[0].strip()] = p[1]
                    else:
                        out[k] = bit
                out[k] = obj
        else:
            kl = k.lower()
            if kl in ("content", "autodelete"):
                final[k] = pay
            elif kl == "author":
                out["author"] = {"name": pay}
            elif kl == "url":
                if not _has_link(pay):
                    raise BadEmbed("embed url invalid")
                out[k] = pay
            elif kl == "timestamp":
                out["timestamp"] = datetime.datetime.now().isoformat()
            else:
                out[k] = pay

    for img_key in ("thumbnail", "image"):
        if out.get(img_key) and isinstance(out[img_key], str):
            if not _has_link(out[img_key]):
                raise BadEmbed(f"{img_key} url invalid")
            out[img_key] = {"url": out[img_key]}

    if out.get("footer"):
        if isinstance(out["footer"], str):
            out["footer"] = {"text": out["footer"]}
        icon = out["footer"].pop("icon", None)
        if icon:
            out["footer"]["icon_url"] = icon.strip("icon: ")

    if out.get("uthor"):
        out["author"] = out.pop("uthor")
        icon = out["author"].pop("icon", None)
        if icon:
            out["author"]["icon_url"] = icon

    if out.get("color"):
        color = out["color"]
        if color.endswith("}"):
            color = color[:-2]
        if not color.startswith("#"):
            try:
                out["color"] = discord.Color(value=int(color))
            except Exception:
                color = f"#{color}"
        try:
            out["color"] = int(discord.Color.from_str(color))
        except Exception as e:
            final["error"] = str(e)
            out["color"] = 0x000001

    if out.get("autodelete"):
        final["delete_after"] = int(out.pop("autodelete"))

    for drop in ("field", "label"):
        out.pop(drop, None)

    if out.get("fields") == []:
        out.pop("fields")

    if out:
        await _validate(out)

    if out:
        final["embed"] = out
    else:
        final.pop("embed", None)

    if sendable and final.get("embed"):
        final["embed"] = discord.Embed.from_dict(final["embed"])

    return final


def to_code(embed: Union[dict, discord.Message, discord.Embed], message: Optional[str] = None) -> str:
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
        for comp in msg.components:
            kids = [comp] if isinstance(comp, discord.Button) else getattr(comp, "children", [])
            for btn in kids:
                if isinstance(btn, discord.Button) and btn.url:
                    code += f"$v{{button: {btn.label or ''} && {btn.url}}}"
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
        s = f"footer: {embed.footer.text}"
        if embed.footer.icon_url:
            s += f" && {embed.footer.icon_url}"
        code += f"$v{{{s}}}"
    if embed.author:
        s = f"author: {embed.author.name}"
        if embed.author.url:
            s += f" && {embed.author.url}"
        if embed.author.icon_url:
            s += f" && {embed.author.icon_url}"
        code += f"$v{{{s}}}"
    if embed.image.url:
        code += f"$v{{image: {embed.image.url}}}"
    if embed.thumbnail.url:
        code += f"$v{{thumbnail: {embed.thumbnail.url}}}"
    if embed.color:
        code += f"$v{{color: #{str(embed.color)}}}".replace("##", "#")
    return code.replace("```", "`​`​`")


class Script:
    """embed template with user and guild vars.
    replaces placeholders then compiles to embed.
    use send() to dispatch to a channel"""

    def __init__(self, template: str, user: Union[discord.Member, discord.User], lastfm: dict = {}):
        self.replacements = {
            "{user}": str(user),
            "{user.mention}": user.mention,
            "{user.name}": user.name,
            "{user.avatar}": user.display_avatar.url,
            "{user.joined_at}": discord.utils.format_dt(user.joined_at, "R"),
            "{user.created_at}": discord.utils.format_dt(user.created_at, "R"),
            "{guild.name}": user.guild.name,
            "{guild.count}": str(user.guild.member_count),
            "{guild.id}": str(user.guild.id),
            "{guild.icon}": user.guild.icon.url if user.guild.icon else "",
            "{guild.boost_count}": str(user.guild.premium_subscription_count),
            "{guild.boost_tier}": str(user.guild.premium_tier),
            **{k: str(v) for k, v in lastfm.items()},
            "{whitespace}": "‎",
        }
        self.template = self._fill(
            template.replace("`​`​`", "```")
                    .replace(r"\n", "\n")
                    .replace("\\n", "\n")
        )

    def _fill(self, t: str) -> str:
        t = t.replace("{embed}", "").replace("$v", "").replace("} {", "}{")
        for k, v in self.replacements.items():
            t = t.replace(k, v)
        return t

    def __str__(self) -> str:
        return self.template

    async def send(self, dest: Union[TextChannel, Thread, discord.Message], **kw) -> discord.Message:
        """send parsed embed to channel or message"""
        data = await parse(self.template, sendable=True)
        if isinstance(dest, (TextChannel, Thread)):
            return await dest.send(**{**data, **kw})
        return await dest.edit(**{**data, **kw})

    async def compile(self) -> bool:
        await parse(self.template)
        return True

    @classmethod
    async def convert(cls, ctx: Context, template: str) -> str:
        s = cls(template, ctx.author)
        await s.compile()
        return str(s)
