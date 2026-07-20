"""Channel converter with fuzzy / partial name matching.

Accepts:
- ``#txt`` / ``txt`` / ``TXT`` (name, case-insensitive)
- ``<#id>`` mentions (and mangled pastes with zero-width chars)
- raw snowflake IDs
- partial names (``txt`` matches ``txt``, ``txt-logs``, etc.)
- fuzzy closest match as last resort

Use ``ChannelConvert`` / ``TextChannelConvert`` in command signatures, or
``resolve_channel(ctx, token)`` from free-form parsers (giveaway start, etc.).

Call ``patch_discord_channel_converters()`` once at bot import so every
``channel: discord.TextChannel`` annotation accepts bare names too.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, Union

import discord
from discord.ext.commands import CommandError, Context, Converter

try:
    from fast_string_match import closest_match
except ImportError:  

    def closest_match(query: str, candidates: Sequence[str]):  # type: ignore
        q = (query or "").lower()
        if not q:
            return None
        for c in candidates:
            if c.lower().startswith(q):
                return c
        for c in candidates:
            if q in c.lower():
                return c
        return None


_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")
_MENTION_RE = re.compile(r"<#(\d{15,22})>")
_ID_RE = re.compile(r"^\d{15,22}$")

_EDGE_JUNK_RE = re.compile(r"^[\s#.<\>\"'`]+|[\s#.<\>\"'`]+$")

ChannelT = Union[
    discord.TextChannel,
    discord.Thread,
    discord.VoiceChannel,
    discord.StageChannel,
    discord.ForumChannel,
    discord.CategoryChannel,
    discord.abc.GuildChannel,
]

_PATCHED = False


def clean_channel_token(token: str) -> str:
    """Strip invisible paste junk, wrapping, and leading # / dots."""
    raw = _INVISIBLE_RE.sub("", (token or "")).strip()
    raw = raw.strip("`\"'")
    
    return raw


def _normalize_name(token: str) -> str:
    """Turn a free-form token into a lowercase channel name candidate."""
    name = clean_channel_token(token)
    
    name = _MENTION_RE.sub("", name)
    name = name.strip("<>")
    
    prev = None
    while prev != name:
        prev = name
        name = _EDGE_JUNK_RE.sub("", name)
    
    while name.startswith("."):
        name = name[1:]
    return name.strip().lower()


def _iter_guild_channels(guild: discord.Guild) -> Iterable[ChannelT]:
    for ch in guild.channels:
        yield ch
    for ch in getattr(guild, "threads", []) or []:
        yield ch


def _name_candidates(channels: Iterable[ChannelT]) -> dict[str, ChannelT]:
    """Map lower name → channel (first wins)."""
    out: dict[str, ChannelT] = {}
    for ch in channels:
        name = getattr(ch, "name", None)
        if not name:
            continue
        out.setdefault(str(name).lower(), ch)
    return out


async def resolve_channel(
    ctx: Context,
    token: str,
    *,
    text_only: bool = False,
    allow_threads: bool = True,
) -> Optional[ChannelT]:
    """Resolve a channel token for *ctx.guild*. Returns None if not found."""
    guild = getattr(ctx, "guild", None)
    if guild is None:
        return None

    raw = clean_channel_token(token)
    if not raw:
        return None

    def _ok(ch: ChannelT | None) -> Optional[ChannelT]:
        if ch is None:
            return None
        if text_only:
            if isinstance(ch, discord.TextChannel):
                return ch
            if isinstance(ch, discord.Thread) and allow_threads:
                return ch
            return None
        return ch

    
    m = _MENTION_RE.search(raw)
    if m:
        cid = int(m.group(1))
        ch = guild.get_channel(cid) or guild.get_thread(cid)
        if ch is None:
            try:
                ch = await guild.fetch_channel(cid)  # type: ignore
            except Exception:
                ch = None
        got = _ok(ch)  # type: ignore
        if got is not None:
            return got

    
    bare_id = clean_channel_token(token).strip("<>#")
    bare_id = _INVISIBLE_RE.sub("", bare_id).strip()
    if _ID_RE.match(bare_id):
        cid = int(bare_id)
        ch = guild.get_channel(cid) or guild.get_thread(cid)
        if ch is None:
            try:
                ch = await guild.fetch_channel(cid)  # type: ignore
            except Exception:
                ch = None
        got = _ok(ch)  # type: ignore
        if got is not None:
            return got

    
    name = _normalize_name(raw)
    if not name:
        return None
    channels = list(_iter_guild_channels(guild))
    if text_only:
        channels = [
            c
            for c in channels
            if isinstance(c, discord.TextChannel)
            or (allow_threads and isinstance(c, discord.Thread))
        ]

    by_name = _name_candidates(channels)

    
    if name in by_name:
        return _ok(by_name[name])

    
    prefix_hits = [c for n, c in by_name.items() if n.startswith(name)]
    if prefix_hits:
        prefix_hits.sort(key=lambda c: len(getattr(c, "name", "") or ""))
        return _ok(prefix_hits[0])

    
    contains_hits = [c for n, c in by_name.items() if name in n]
    if contains_hits:
        contains_hits.sort(key=lambda c: len(getattr(c, "name", "") or ""))
        return _ok(contains_hits[0])

    
    match = closest_match(name, list(by_name.keys()))
    if match and match in by_name:
        return _ok(by_name[match])

    return None


class ChannelConvert(Converter):
    """Convert to any guild channel (text, voice, category, forum, thread)."""

    async def convert(self, ctx: Context, arg: str) -> ChannelT:
        ch = await resolve_channel(ctx, arg, text_only=False)
        if ch is not None:
            return ch
        raise CommandError(f"**can't** find channel **{arg}**")


class TextChannelConvert(Converter):
    """Convert to a text channel or thread (messages can be sent)."""

    async def convert(
        self, ctx: Context, arg: str
    ) -> Union[discord.TextChannel, discord.Thread]:
        ch = await resolve_channel(ctx, arg, text_only=True, allow_threads=True)
        if isinstance(ch, (discord.TextChannel, discord.Thread)):
            return ch
        raise CommandError(f"**can't** find text channel **{arg}**")


def _make_soft_text_converter():
    from discord.ext.commands import TextChannelConverter as Base

    class SoftTextChannelConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str) -> discord.TextChannel:
            
            ch = await resolve_channel(ctx, argument, text_only=True, allow_threads=False)
            if isinstance(ch, discord.TextChannel):
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find text channel **{argument}**")

    return SoftTextChannelConverter


def _make_soft_guild_channel_converter():
    from discord.ext.commands import GuildChannelConverter as Base

    class SoftGuildChannelConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str):
            ch = await resolve_channel(ctx, argument, text_only=False)
            if ch is not None:
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find channel **{argument}**")

    return SoftGuildChannelConverter


def _make_soft_voice_converter():
    from discord.ext.commands import VoiceChannelConverter as Base

    class SoftVoiceChannelConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str) -> discord.VoiceChannel:
            ch = await resolve_channel(ctx, argument, text_only=False)
            if isinstance(ch, discord.VoiceChannel):
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find voice channel **{argument}**")

    return SoftVoiceChannelConverter


def _make_soft_thread_converter():
    from discord.ext.commands import ThreadConverter as Base

    class SoftThreadConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str) -> discord.Thread:
            ch = await resolve_channel(ctx, argument, text_only=True, allow_threads=True)
            if isinstance(ch, discord.Thread):
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find thread **{argument}**")

    return SoftThreadConverter


def _make_soft_category_converter():
    from discord.ext.commands import CategoryChannelConverter as Base

    class SoftCategoryChannelConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str) -> discord.CategoryChannel:
            ch = await resolve_channel(ctx, argument, text_only=False)
            if isinstance(ch, discord.CategoryChannel):
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find category **{argument}**")

    return SoftCategoryChannelConverter


def _make_soft_forum_converter():
    from discord.ext.commands import ForumChannelConverter as Base

    class SoftForumChannelConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str) -> discord.ForumChannel:
            ch = await resolve_channel(ctx, argument, text_only=False)
            if isinstance(ch, discord.ForumChannel):
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find forum **{argument}**")

    return SoftForumChannelConverter


def _make_soft_stage_converter():
    from discord.ext.commands import StageChannelConverter as Base

    class SoftStageChannelConverter(Base):  # type: ignore
        async def convert(self, ctx: Context, argument: str) -> discord.StageChannel:
            ch = await resolve_channel(ctx, argument, text_only=False)
            if isinstance(ch, discord.StageChannel):
                return ch
            try:
                return await super().convert(ctx, argument)
            except Exception:
                raise CommandError(f"**can't** find stage channel **{argument}**")

    return SoftStageChannelConverter


def patch_discord_channel_converters() -> None:
    """Monkey-patch discord.py converters so bare names work everywhere.

    Safe to call multiple times. Should run at bot import time (before cogs load).
    """
    global _PATCHED
    if _PATCHED:
        return

    import discord.ext.commands as cmds
    import discord.ext.commands.converter as conv

    SoftText = _make_soft_text_converter()
    SoftGuild = _make_soft_guild_channel_converter()
    SoftVoice = _make_soft_voice_converter()
    SoftThread = _make_soft_thread_converter()
    SoftCategory = _make_soft_category_converter()
    SoftForum = _make_soft_forum_converter()
    SoftStage = _make_soft_stage_converter()

    
    conv.TextChannelConverter = SoftText  # type: ignore
    conv.GuildChannelConverter = SoftGuild  # type: ignore
    conv.VoiceChannelConverter = SoftVoice  # type: ignore
    conv.ThreadConverter = SoftThread  # type: ignore
    conv.CategoryChannelConverter = SoftCategory  # type: ignore
    conv.ForumChannelConverter = SoftForum  # type: ignore
    conv.StageChannelConverter = SoftStage  # type: ignore

    
    cmds.TextChannelConverter = SoftText  # type: ignore
    cmds.GuildChannelConverter = SoftGuild  # type: ignore
    cmds.VoiceChannelConverter = SoftVoice  # type: ignore
    cmds.ThreadConverter = SoftThread  # type: ignore
    cmds.CategoryChannelConverter = SoftCategory  # type: ignore
    try:
        cmds.ForumChannelConverter = SoftForum  # type: ignore
    except Exception:
        pass
    try:
        cmds.StageChannelConverter = SoftStage  # type: ignore
    except Exception:
        pass

    
    mapping = conv.CONVERTER_MAPPING
    mapping[discord.TextChannel] = SoftText
    mapping[discord.abc.GuildChannel] = SoftGuild
    mapping[discord.VoiceChannel] = SoftVoice
    mapping[discord.Thread] = SoftThread
    mapping[discord.CategoryChannel] = SoftCategory
    mapping[discord.ForumChannel] = SoftForum
    mapping[discord.StageChannel] = SoftStage

    _PATCHED = True
