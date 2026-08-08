from __future__ import annotations

import re
from pathlib import Path

import discord
from discord.ext import commands
from discord.ext.commands import CommandError

from core.patches.alias import CmdConverter
from core.tools.models import ScriptType


_EXT_ROOT = Path(__file__).resolve().parents[2] / "ext"
_MODULE_ALIASES = {
    "servers": "server",
    "infos": "information",
    "info": "information",
    "mods": "moderation",
    "gw": "giveaway",
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


class _EventMapping(dict):
    def __missing__(self, key):
        value = (str(key).replace("_", " "), "")
        self[key] = value
        return value


EVENT_MAPPING = _EventMapping(
    {
        "y/n": ("y/n", "Toggle upvote/downvote to messages."),
        "v/s": ("v/s", "Toggle left arrow/right arrow to messages."),
        "afk": ("afk", "Toggle away messages when pinging AFK members."),
        "previousreaction": (
            "previousreaction",
            "Toggle any previous reaction triggers.",
        ),
        "reactiontrigger": (
            "reactiontrigger",
            "Toggle any reaction triggers.",
        ),
        "autoresponder": ("autoresponder", "Toggle all auto responders."),
        "commandfailure": (
            "commandfailure",
            "Toggle failed command execution messages.",
        ),
        "snipe": ("snipe", "Toggle messages from being sniped completely."),
        "cleverbot": ("cleverbot", "Toggle clever bot conversations."),
        "automodmessage": (
            "automodmessage",
            "Toggle vain auto-mod messages upon user punishment.",
        ),
        "instagram": ("instagram", "Toggle Instagram reposting from members."),
        "tiktok": ("tiktok", "Toggle TikTok reposting from members."),
        "grailed": ("grailed", "Toggle Grailed reposting from members."),
        "twitch": ("twitch", "Toggle Twitch reposting from members."),
        "streamable": ("streamable", "Toggle Streamable reposting from members."),
        "twitter": ("twitter", "Toggle Twitter/X reposting from members."),
        "medal": ("medal", "Toggle Medal reposting from members."),
        "soundcloud": ("soundcloud", "Toggle SoundCloud reposting from members."),
        "tumblr": ("tumblr", "Toggle Tumblr reposting from members."),
        "shorts": ("shorts", "Toggle Shorts reposting from members."),
        "kick": ("kick", "Toggle Kick reposting from members."),
        "youtube": ("youtube", "Toggle YouTube reposting from members."),
        "reddit": ("reddit", "Toggle Reddit reposting from members."),
    }
)

_EVENT_ALIASES = {
    "yn": "y/n",
    "upvote": "y/n",
    "downvote": "y/n",
    "vs": "v/s",
    "leftright": "v/s",
    "previousreactions": "previousreaction",
    "reactiontriggers": "reactiontrigger",
    "commandfail": "commandfailure",
    "command_fail": "commandfailure",
    "automod": "automodmessage",
}


def normalize_event_name(value: str) -> str:
    normalized = _normalize(value)
    if normalized in _EVENT_ALIASES:
        return _EVENT_ALIASES[normalized]
    for event_name in EVENT_MAPPING:
        if _normalize(event_name) == normalized:
            return event_name
    return normalized


def _available_modules() -> set[str]:
    if not _EXT_ROOT.exists():
        return set()
    modules = {
        item.name
        for item in _EXT_ROOT.iterdir()
        if item.is_dir()
        and (item / "__init__.py").exists()
        and item.name not in {"__pycache__", "models"}
    }
    modules.update(_MODULE_ALIASES.values())
    return modules


class CommandConverter(CmdConverter):
    """legacy alias for the custom command converter."""


class EventConverter(commands.Converter):
    """convert an event label or alias to its canonical event key."""

    async def convert(self, ctx: commands.Context, argument: str) -> str:
        event = normalize_event_name(argument)
        if event in EVENT_MAPPING:
            return event
        normalized = _normalize(argument)
        if not normalized:
            raise CommandError("provide a valid event name")
        return normalized


class ModuleConverter(commands.Converter):
    """convert a module label to the current module key."""

    async def convert(self, ctx: commands.Context, argument: str) -> str:
        normalized = argument.lower().replace(" ", "_").replace("-", "_")
        normalized = _MODULE_ALIASES.get(normalized, normalized)
        if normalized in _available_modules():
            return normalized
        if not normalized:
            raise CommandError("provide a valid module name")
        return normalized


class EmbedConverter(commands.Converter):
    """Pass embed/container/plain/discohook JSON through as ScriptType."""

    async def convert(self, ctx: commands.Context, argument: str):
        from core.tools.embed import maybe_wrap_embed_script

        
        return ScriptType(maybe_wrap_embed_script(argument))


class MessageLinkConverter(commands.MessageConverter):
    """legacy alias around discord.py's message converter."""

    fallback = None


class FakePermissionConverter(commands.Converter):
    """parse a list of fake permissions from a free-form string."""

    _valid = set(discord.Permissions.VALID_FLAGS) | {"guild_owner", "server_owner"}

    async def convert(self, ctx: commands.Context, argument: str) -> list[str]:
        permissions = [
            value.lower()
            for value in re.split(r"[\s,]+", argument.strip())
            if value.strip()
        ]
        if not permissions:
            raise CommandError("provide at least one permission")

        invalid = [value for value in permissions if value not in self._valid]
        if invalid:
            joined = ", ".join(f"`{value}`" for value in invalid)
            raise CommandError(f"invalid fake permission(s): {joined}")
        return permissions
