from __future__ import annotations

import re
from pathlib import Path

import discord
from discord.ext import commands
from discord.ext.commands import CommandError

from core.patches.alias import CmdConverter
from core.tools.models import ScriptType
from lib.classes.converters import EVENT_MAPPING, normalize_event_name


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
