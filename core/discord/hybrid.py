from __future__ import annotations

import contextlib
import functools
import inspect
import logging
from typing import Any, Callable, Iterable

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("vain.hybrid")

_DESCRIPTIONS_ATTR = "__vain_descriptions__"
_SLASH_HYBRID_ATTR = "__vain_slash_hybrid__"
_FAMILY_ROOT_ATTR = "__vain_family_root__"
_FAMILY_HELP_NAME_ATTR = "__vain_family_help_name__"


def linked_family(root: str, *, help_name: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """link a hybrid command to a virtual family root for help and prefix routing."""
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, _FAMILY_ROOT_ATTR, root)
        if help_name:
            setattr(fn, _FAMILY_HELP_NAME_ATTR, help_name)
        return fn

    return deco


def _copy_link_meta(cmd: commands.Command, fn: Callable[..., Any]) -> None:
    root = getattr(fn, _FAMILY_ROOT_ATTR, None)
    help_name = getattr(fn, _FAMILY_HELP_NAME_ATTR, None)
    if root is not None:
        cmd.__vain_family_root__ = root
    if help_name is not None:
        cmd.__vain_family_help_name__ = help_name
    callback = getattr(cmd, "callback", None)
    if callback is not None:
        if root is not None:
            callback.__vain_family_root__ = root
        if help_name is not None:
            callback.__vain_family_help_name__ = help_name


def family_root(cmd: commands.Command) -> str | None:
    return getattr(cmd, _FAMILY_ROOT_ATTR, None) or getattr(
        getattr(cmd, "callback", None), _FAMILY_ROOT_ATTR, None
    )


def family_help_name(cmd: commands.Command) -> str | None:
    return getattr(cmd, _FAMILY_HELP_NAME_ATTR, None) or getattr(
        getattr(cmd, "callback", None), _FAMILY_HELP_NAME_ATTR, None
    )


def command_display_name(cmd: commands.Command) -> str:
    return family_help_name(cmd) or cmd.qualified_name


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
    guilds: bool | None = None,
    dms: bool | None = None,
    groupchats: bool | None = None,
) -> tuple[bool, bool, bool]:
    """map flags to guilds dms private_channels booleans"""
    if guild_only:
        return True, False, False
    explicit = any(v is not None for v in (guilds, dms, groupchats))
    if not explicit:
        return True, True, True
    return (
        guilds if guilds is not None else True,
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

    wrapper.__globals__ = fn.__globals__
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


def _pop_hybrid_attrs(attrs: dict) -> tuple[str | None, dict, bool, bool | None, bool | None, bool | None, bool, bool]:
    example = attrs.pop("example", None)
    parameters = attrs.pop("parameters", {})
    guild_only = attrs.pop("guild_only", False)
    guilds = attrs.pop("guilds", None)
    dms = attrs.pop("dms", None)
    groupchats = attrs.pop("groupchats", None)
    slash = attrs.pop("slash", True)
    is_group = attrs.pop("group", False)
    attrs.pop("dm_enabled", None)
    attrs.pop("cls", None)
    if not slash:
        attrs["with_app_command"] = False
    return example, parameters, guild_only, guilds, dms, groupchats, slash, is_group


def hybrid(name: str | None = None, **attrs: Any):
    """hybrid command or group factory.
    pass group=True for slash+prefix command groups.
    auto defers interactions and applies slash context flags"""
    is_group = attrs.pop("group", False)
    if is_group or "invoke_without_command" in attrs:
        if "invoke_without_command" not in attrs:
            attrs["invoke_without_command"] = True
        return _hybrid_group(name, **attrs)
    return _hybrid_command(name, **attrs)


def _hybrid_command(name: str | None = None, **attrs: Any):
    example, params, guild_only, guilds, dms, groupchats, _, _ = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(guild_only=guild_only, guilds=guilds, dms=dms, groupchats=groupchats)

    def deco(fn: Callable[..., Any]) -> commands.HybridCommand:
        prepared = _inject_descriptions(_wrap_callback(fn, guilds=guilds, dms=_dms, groupchats=_gcs), params)
        cmd = _try_register(commands.hybrid_command, prepared, name=name, attrs=attrs)
        _copy_link_meta(cmd, fn)
        cmd.example = example
        cmd.parameters = params
        return cmd

    return deco


def _hybrid_group(name: str | None = None, **attrs: Any):
    example, params, guild_only, guilds, dms, groupchats, _, _ = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(guild_only=guild_only, guilds=guilds, dms=dms, groupchats=groupchats)

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
            sub_servers = kw.pop("guilds", None)
            sub_dms = kw.pop("dms", None)
            sub_gcs = kw.pop("groupchats", None)
            if not kw.pop("slash", True):
                kw["with_app_command"] = False
            kw.pop("dm_enabled", None)
            kw.pop("cls", None)
            sg, sd, sc = _resolve_contexts(guild_only=sub_guild_only, guilds=sub_servers, dms=sub_dms, groupchats=sub_gcs)

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


def slash_hybrid(name: str | None = None, **attrs: Any):
    """slash-only command: no prefix registration, added in cog_load."""
    description = attrs.get("description")
    example, params, guild_only, guilds, dms, groupchats, _, _ = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(
        guild_only=guild_only,
        guilds=guilds,
        dms=dms,
        groupchats=groupchats,
    )

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            fn,
            _SLASH_HYBRID_ATTR,
            {
                "name": name or fn.__name__,
                "description": (description or fn.__doc__ or "…").strip(),
                "example": example,
                "parameters": params,
                "guilds": guilds,
                "dms": _dms,
                "groupchats": _gcs,
            },
        )
        return fn

    return deco


def _slash_kwargs(method: Callable[..., Any], namespace: Any) -> dict[str, Any]:
    if namespace is None:
        return {}
    kwargs: dict[str, Any] = {}
    for param_name in list(inspect.signature(method).parameters)[2:]:
        if hasattr(namespace, param_name):
            kwargs[param_name] = getattr(namespace, param_name)
    return kwargs


def register_cog_slash_hybrids(cog: commands.Cog) -> None:
    """register slash_hybrid methods on the cog with the bot command tree."""
    from core.discord.ctx import Context

    bot = cog.bot
    registered: list[str] = []

    for attr_name in dir(cog):
        method = getattr(cog, attr_name, None)
        if method is None or not inspect.ismethod(method):
            continue
        fn = getattr(method, "__func__", method)
        meta = getattr(fn, _SLASH_HYBRID_ATTR, None)
        if meta is None:
            continue

        async def slash_invoke(
            interaction: discord.Interaction,
            *,
            _method: Callable[..., Any] = method,
            _meta: dict[str, Any] = meta,
        ) -> None:
            if not interaction.response.is_done():
                with contextlib.suppress(discord.NotFound, discord.HTTPException):
                    await interaction.response.defer()
            ctx = await bot.get_context(interaction, cls=Context)
            await _method(ctx, **_slash_kwargs(_method, interaction.namespace))

        prepared = _inject_descriptions(
            app_commands.allowed_contexts(
                guilds=meta["guilds"],
                dms=meta["dms"],
                private_channels=meta["groupchats"],
            )(
                app_commands.allowed_installs(guilds=True, users=True)(slash_invoke)
            ),
            meta["parameters"],
        )
        app_cmd = app_commands.Command(
            name=meta["name"],
            description=meta["description"],
            callback=prepared,
        )
        app_cmd.binding = cog
        with contextlib.suppress(app_commands.CommandAlreadyRegistered):
            bot.tree.add_command(app_cmd)
        registered.append(meta["name"])

    cog.__slash_hybrid_names__ = registered


def rewrite_linked_prefix(content: str, prefixes: Iterable[str]) -> str | None:
    """rewrite virtual family invocations to their real hybrid command names."""
    if not content:
        return None
    prefix = next((pfx for pfx in sorted(prefixes, key=len, reverse=True) if content.startswith(pfx)), None)
    if prefix is None:
        return None
    rest = content[len(prefix) :].strip()
    if not rest:
        return None
    tokens = rest.split()
    head = tokens[0].lower()
    if head not in {"tictactoe", "ttt", "tic-tac-toe"}:
        return None
    if len(tokens) < 2:
        return None
    sub = tokens[1].lower()
    tail = " ".join(tokens[2:])
    if sub in {"statistics", "stats", "s"}:
        target = "tictactoestatistics"
    elif sub in {"leaderboard", "lb", "leader"}:
        target = "tictactoeleaderboard"
    else:
        return None
    body = f"{target} {tail}".strip()
    return f"{prefix}{body}"


def unregister_cog_slash_hybrids(cog: commands.Cog) -> None:
    for name in getattr(cog, "__slash_hybrid_names__", ()):
        with contextlib.suppress(Exception):
            cog.bot.tree.remove_command(name)
