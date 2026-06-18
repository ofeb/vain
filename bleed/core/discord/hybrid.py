from __future__ import annotations

import contextlib
import functools
import logging
from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("bleed.hybrid")

_DESCRIPTIONS_ATTR = "__bleed_descriptions__"


def describe(**kw: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """attach slash param descriptions to callback"""
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        merged = dict(getattr(fn, _DESCRIPTIONS_ATTR, {}))
        merged.update(kw)
        setattr(fn, _DESCRIPTIONS_ATTR, merged)
        return fn
    return deco


def _inject_descriptions(fn: Callable[..., Any], params: dict[str, Any]) -> Callable[..., Any]:
    descs: dict[str, str] = {k: v for k, v in params.items() if isinstance(v, str)}
    descs.update(getattr(fn, _DESCRIPTIONS_ATTR, {}))
    return app_commands.describe(**descs)(fn) if descs else fn


def _resolve_contexts(
    *,
    guild_only: bool = False,
    servers: bool | None = None,
    dms: bool | None = None,
    groupchats: bool | None = None,
) -> tuple[bool, bool, bool]:
    """map flags to guilds dms private_channels booleans"""
    if guild_only:
        return True, False, False
    explicit = any(v is not None for v in (servers, dms, groupchats))
    if not explicit:
        return True, True, True
    return (
        servers if servers is not None else True,
        dms if dms is not None else True,
        groupchats if groupchats is not None else True,
    )


def _wrap_callback(
    fn: Callable[..., Any],
    *,
    guilds: bool,
    dms: bool,
    groupchats: bool,
) -> Callable[..., Any]:
    """apply slash context flags and auto defer interactions"""
    fn = app_commands.allowed_contexts(guilds=guilds, dms=dms, private_channels=groupchats)(fn)
    fn = app_commands.allowed_installs(guilds=True, users=True)(fn)
    if guilds and not dms and not groupchats:
        fn = commands.guild_only()(fn)

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any):
        ctx = next((a for a in args if isinstance(a, commands.Context)), None)
        if ctx is not None and getattr(ctx, "interaction", None) is not None:
            inter = ctx.interaction
            if not inter.response.is_done():
                with contextlib.suppress(discord.NotFound, discord.HTTPException):
                    await inter.response.defer()
        return await fn(*args, **kwargs)

    return wrapper


def _try_register(factory, prepared, *, name, attrs):
    """register hybrid command, fallback to prefix-only on error"""
    try:
        cmd = factory(name=name, **attrs)(prepared)
        if not getattr(cmd, "app_command", None) and attrs.get("with_app_command", True):
            log.warning("hybrid /%s registered prefix-only (no app_command)", cmd.name)
        return cmd
    except (TypeError, ValueError) as e:
        log.warning("hybrid /%s slash failed (%s), prefix-only", name, e)
        attrs = {**attrs, "with_app_command": False}
        return factory(name=name, **attrs)(prepared)


class BotCommand(commands.Command):
    """command subclass with example and parameters"""
    def __init__(self, fn: Callable[..., Any], /, **kw: Any) -> None:
        self.example: str | None = kw.pop("example", None)
        self.parameters: dict[str, Any] = kw.pop("parameters", {})
        super().__init__(fn, **kw)


class BotGroup(commands.Group, BotCommand):
    """group subclass that spawns BotCommand children"""
    def command(self, *args: Any, **kw: Any):
        def deco(fn):
            kw.setdefault("parent", self)
            result = command(*args, **kw)(fn)
            self.add_command(result)
            return result
        return deco

    def group(self, *args: Any, **kw: Any):
        def deco(fn):
            kw.setdefault("parent", self)
            result = group(*args, **kw)(fn)
            self.add_command(result)
            return result
        return deco


def command(name: str | None = None, **attrs: Any):
    """prefix-only command using BotCommand"""
    attrs.setdefault("cls", BotCommand)
    return commands.command(name=name, **attrs)


def group(name: str | None = None, **attrs: Any):
    """prefix-only group using BotGroup"""
    attrs.setdefault("cls", BotGroup)
    return commands.command(name=name, **attrs)


def _pop_hybrid_attrs(attrs: dict) -> tuple[str | None, dict, bool, bool | None, bool | None, bool | None, bool]:
    example = attrs.pop("example", None)
    parameters = attrs.pop("parameters", {})
    guild_only = attrs.pop("guild_only", False)
    servers = attrs.pop("servers", None)
    dms = attrs.pop("dms", None)
    groupchats = attrs.pop("groupchats", None)
    slash = attrs.pop("slash", True)
    attrs.pop("dm_enabled", None)
    attrs.pop("cls", None)
    if not slash:
        attrs["with_app_command"] = False
    return example, parameters, guild_only, servers, dms, groupchats, slash


def hybrid(name: str | None = None, **attrs: Any):
    """hybrid command or group factory.
    pass invoke_without_command to make it a group.
    auto defers interactions and applies slash context flags"""
    if "invoke_without_command" in attrs:
        return _hybrid_group(name, **attrs)
    return _hybrid_command(name, **attrs)


def _hybrid_command(name: str | None = None, **attrs: Any):
    example, params, guild_only, servers, dms, groupchats, _ = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(guild_only=guild_only, servers=servers, dms=dms, groupchats=groupchats)

    def deco(fn: Callable[..., Any]) -> commands.HybridCommand:
        prepared = _inject_descriptions(_wrap_callback(fn, guilds=guilds, dms=_dms, groupchats=_gcs), params)
        cmd = _try_register(commands.hybrid_command, prepared, name=name, attrs=attrs)
        cmd.example = example
        cmd.parameters = params
        return cmd

    return deco


def _hybrid_group(name: str | None = None, **attrs: Any):
    example, params, guild_only, servers, dms, groupchats, _ = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(guild_only=guild_only, servers=servers, dms=dms, groupchats=groupchats)

    def deco(fn: Callable[..., Any]) -> commands.HybridGroup:
        prepared = _inject_descriptions(_wrap_callback(fn, guilds=guilds, dms=_dms, groupchats=_gcs), params)
        grp = _try_register(commands.hybrid_group, prepared, name=name, attrs=attrs)
        grp.example = example
        grp.parameters = params
        _orig_command = grp.command

        def sub_command(*args: Any, **kw: Any):
            sub_example = kw.pop("example", None)
            sub_params = kw.pop("parameters", {})
            sub_guild_only = kw.pop("guild_only", False)
            sub_servers = kw.pop("servers", None)
            sub_dms = kw.pop("dms", None)
            sub_gcs = kw.pop("groupchats", None)
            if not kw.pop("slash", True):
                kw["with_app_command"] = False
            kw.pop("dm_enabled", None)
            kw.pop("cls", None)
            sg, sd, sc = _resolve_contexts(guild_only=sub_guild_only, servers=sub_servers, dms=sub_dms, groupchats=sub_gcs)

            def sub_deco(sub_fn):
                sub_prepared = _inject_descriptions(_wrap_callback(sub_fn, guilds=sg, dms=sd, groupchats=sc), sub_params)
                cmd_name = kw.get("name") or sub_fn.__name__
                try:
                    cmd = _orig_command(*args, **kw)(sub_prepared)
                except (TypeError, ValueError) as e:
                    log.warning("hybrid /%s slash failed (%s), prefix-only", cmd_name, e)
                    fallback_kw = {**kw, "with_app_command": False}
                    cmd = _orig_command(*args, **fallback_kw)(sub_prepared)
                cmd.example = sub_example
                cmd.parameters = sub_params
                return cmd

            return sub_deco

        grp.command = sub_command
        return grp

    return deco
