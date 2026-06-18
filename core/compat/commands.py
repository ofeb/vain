from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import discord
from discord.ext import commands
from discord.ext.commands import CommandError, MissingPermissions

from core.patches.alias import CmdConverter
from lib.classes.converters import EVENT_MAPPING, normalize_event_name

_PATCHED = False
_SPECIAL_PERMISSIONS = {"guild_owner", "server_owner"}
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


async def _fake_permissions(ctx) -> set[str]:
    role_ids = [role.id for role in getattr(ctx.author, "roles", ())]
    if not role_ids:
        return set()

    try:
        rows = await ctx.bot.db.fetch(
            """SELECT permissions FROM fake_permissions
               WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])""",
            ctx.guild.id,
            role_ids,
        )
    except Exception:
        return set()

    collected: set[str] = set()
    for row in rows:
        raw = row[0] if isinstance(row, tuple) else getattr(row, "permissions", None)
        if raw is None:
            continue
        if isinstance(raw, str):
            try:
                values = json.loads(raw)
            except json.JSONDecodeError:
                values = [piece for piece in re.split(r"[\s,]+", raw) if piece]
        else:
            values = list(raw)
        collected.update(str(value).lower() for value in values)
    return collected


def has_permissions(**permissions):
    required = dict(permissions)

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")

        if await ctx.bot.is_owner(ctx.author):
            return True

        owner_required = any(required.get(name) for name in _SPECIAL_PERMISSIONS)
        missing = []
        if owner_required and ctx.author.id != ctx.guild.owner_id:
            missing.append("server owner")

        guild_permissions = ctx.author.guild_permissions
        for name, enabled in required.items():
            if not enabled or name in _SPECIAL_PERMISSIONS:
                continue
            if not getattr(guild_permissions, name, False):
                missing.append(name)

        if not missing:
            return True

        fake_permissions = await _fake_permissions(ctx)
        if "administrator" in fake_permissions:
            return True

        unresolved = []
        for name in missing:
            lookup = name.replace(" ", "_")
            if lookup == "server_owner":
                if ctx.author.id == ctx.guild.owner_id:
                    continue
            elif lookup in fake_permissions:
                continue
            else:
                unresolved.append(name)

        if not unresolved:
            return True

        if unresolved == ["server owner"]:
            raise CommandError(
                f"you must be the **server owner** to use `{ctx.command.qualified_name}`"
            )

        raise MissingPermissions([name.replace(" ", "_") for name in unresolved])

    return commands.check(predicate)


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
    """pass embed script bodies through while preserving `.script` access."""

    async def convert(self, ctx: commands.Context, argument: str):
        from core.tools.models import ScriptType

        return ScriptType(argument)


class MessageLinkConverter(commands.MessageConverter):
    """legacy alias around discord.py's message converter."""

    fallback = None


class FakePermissionConverter(commands.Converter):
    """parse a list of fake permissions from a free-form string."""

    _valid = set(discord.Permissions.VALID_FLAGS) | _SPECIAL_PERMISSIONS

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


def install() -> None:
    global _PATCHED
    if _PATCHED:
        return

    commands.has_permissions = has_permissions
    commands.Boolean = bool
    commands.CommandConverter = CommandConverter
    commands.EventConverter = EventConverter
    commands.ModuleConverter = ModuleConverter
    commands.EmbedConverter = EmbedConverter
    commands.MessageLinkConverter = MessageLinkConverter
    commands.FakePermissionConverter = FakePermissionConverter

    _PATCHED = True


install()
