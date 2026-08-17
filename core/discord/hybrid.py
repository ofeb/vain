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
    """Apply slash context flags and auto-defer interactions.

    Do **not** assign ``wrapper.__signature__ = inspect.signature(...)``.
    discord.py only builds proper ``commands.Parameter`` (with ``.converter``)
    when it walks ``__wrapped__``. A raw inspect.Signature makes HybridCommand
    crash with: AttributeError: 'Parameter' object has no attribute 'converter'.
    """
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
                try:
                    await inter.response.defer()
                except (discord.NotFound, discord.HTTPException):
                    pass
        return await fn(*args, **kwargs)

    
    if hasattr(wrapper, "__signature__"):
        try:
            delattr(wrapper, "__signature__")
        except Exception:
            try:
                del wrapper.__signature__
            except Exception:
                pass
    return wrapper


def _try_register(factory, prepared, *, name, attrs):
    """register hybrid command, fallback to prefix-only on error"""
    try:
        cmd = factory(name=name, **attrs)(prepared)
        if not getattr(cmd, "app_command", None) and attrs.get("with_app_command", True):
            log.warning("hybrid /%s registered prefix-only (no app_command)", cmd.name)
        return cmd
    except (TypeError, ValueError, AttributeError) as e:
        
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
            hybrid_cmd = getattr(self, "_hybrid_command_override", None)
            if hybrid_cmd is not None:
                result = hybrid_cmd(*args, **kw)(fn)
            else:
                result = command(*args, **kw)(fn)
            self.add_command(result)
            return result
        return deco

    def group(self, *args: Any, **kw: Any):
        def deco(fn):
            kw.setdefault("parent", self)
            hybrid_grp = getattr(self, "_hybrid_group_override", None)
            if hybrid_grp is not None:
                result = hybrid_grp(*args, **kw)(fn)
            else:
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


def _normalize_aliases(raw: Any) -> list[str]:
    """Coerce ``aliases`` to a clean ``list[str]`` for discord.py.

    Accepts list/tuple/set/str. A bare string is treated as **one** alias
    (not character-iterated). Empty/duplicate values are dropped.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        items: Iterable[Any] = (raw,)
    elif isinstance(raw, Iterable):
        items = raw
    else:
        items = (raw,)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        alias = str(item).strip()
        if not alias:
            continue
        key = alias.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def _apply_aliases(cmd: commands.Command, aliases: list[str] | None) -> None:
    """Ensure prefix aliases stick on the command object after factory create."""
    if aliases is None:
        return
    cleaned = _normalize_aliases(aliases)
    try:
        cmd.aliases = cleaned
    except Exception:
        try:
            object.__setattr__(cmd, "aliases", cleaned)
        except Exception:
            log.warning("could not set aliases=%s on %s", cleaned, getattr(cmd, "name", cmd))


def _pop_hybrid_attrs(attrs: dict) -> tuple[str | None, dict, bool, bool | None, bool | None, bool | None, bool, bool, list[str] | None]:
    example = attrs.pop("example", None)
    parameters = attrs.pop("parameters", {})
    guild_only = attrs.pop("guild_only", False)
    guilds = attrs.pop("guilds", None)
    dms = attrs.pop("dms", None)
    groupchats = attrs.pop("groupchats", None)
    slash = attrs.pop("slash", True)
    is_group = attrs.pop("group", False)
    
    
    aliases_raw = attrs.pop("aliases", None)
    aliases: list[str] | None
    if aliases_raw is None:
        aliases = None
    else:
        aliases = _normalize_aliases(aliases_raw)
        attrs["aliases"] = list(aliases)
    attrs.pop("dm_enabled", None)
    attrs.pop("cls", None)
    if not slash:
        attrs["with_app_command"] = False
    return example, parameters, guild_only, guilds, dms, groupchats, slash, is_group, aliases


def hybrid(name: str | None = None, *, aliases: Iterable[str] | str | None = None, **attrs: Any):
    """hybrid command or group factory.

    Parameters
    ----------
    name:
        Command name (defaults to the function name).
    aliases:
        Prefix aliases (e.g. ``aliases=["cs"]`` for ``clearsnipe``). Forwarded
        to discord.py and force-applied on the resulting command so they always
        register in ``bot.all_commands`` / ``bot.get_command``.
    group:
        Pass ``group=True`` (or ``invoke_without_command=...``) for a hybrid group.
    """
    if aliases is not None:
        attrs["aliases"] = aliases
    is_group = attrs.pop("group", False)
    if is_group or "invoke_without_command" in attrs:
        if "invoke_without_command" not in attrs:
            attrs["invoke_without_command"] = True
        return _hybrid_group(name, **attrs)
    return _hybrid_command(name, **attrs)


def _hybrid_command(name: str | None = None, **attrs: Any):
    example, params, guild_only, guilds, dms, groupchats, _, _, aliases = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(guild_only=guild_only, guilds=guilds, dms=dms, groupchats=groupchats)

    def deco(fn: Callable[..., Any]) -> commands.HybridCommand:
        prepared = _inject_descriptions(_wrap_callback(fn, guilds=guilds, dms=_dms, groupchats=_gcs), params)
        cmd = _try_register(commands.hybrid_command, prepared, name=name, attrs=attrs)
        _apply_aliases(cmd, aliases)
        _copy_link_meta(cmd, fn)
        cmd.example = example
        cmd.parameters = params
        return cmd

    return deco


def _hybrid_group(name: str | None = None, **attrs: Any):
    example, params, guild_only, guilds, dms, groupchats, _, _, aliases = _pop_hybrid_attrs(attrs)
    guilds, _dms, _gcs = _resolve_contexts(guild_only=guild_only, guilds=guilds, dms=dms, groupchats=groupchats)

    def deco(fn: Callable[..., Any]) -> commands.HybridGroup:
        prepared = _inject_descriptions(_wrap_callback(fn, guilds=guilds, dms=_dms, groupchats=_gcs), params)
        grp = _try_register(commands.hybrid_group, prepared, name=name, attrs=attrs)
        _apply_aliases(grp, aliases)
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
            sub_aliases_raw = kw.pop("aliases", None)
            sub_aliases = (
                None if sub_aliases_raw is None else _normalize_aliases(sub_aliases_raw)
            )
            if sub_aliases is not None:
                kw["aliases"] = list(sub_aliases)
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
                _apply_aliases(cmd, sub_aliases)
                cmd.example = sub_example
                cmd.parameters = sub_params
                return cmd

            return sub_deco

        grp.command = sub_command
        grp._hybrid_command_override = sub_command

        _orig_group = getattr(grp, "group", None)
        if callable(_orig_group):

            def sub_group(*args: Any, **kw: Any):
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
                sub_aliases_raw = kw.pop("aliases", None)
                sub_aliases = (
                    None if sub_aliases_raw is None else _normalize_aliases(sub_aliases_raw)
                )
                if sub_aliases is not None:
                    kw["aliases"] = list(sub_aliases)
                if "invoke_without_command" not in kw:
                    kw["invoke_without_command"] = True
                sg, sd, sc = _resolve_contexts(
                    guild_only=sub_guild_only,
                    guilds=sub_servers,
                    dms=sub_dms,
                    groupchats=sub_gcs,
                )

                def sub_deco(sub_fn):
                    sub_prepared = _inject_descriptions(
                        _wrap_callback(sub_fn, guilds=sg, dms=sd, groupchats=sc),
                        sub_params,
                    )
                    gname = kw.get("name") or sub_fn.__name__
                    try:
                        nested = _orig_group(*args, **kw)(sub_prepared)
                    except (TypeError, ValueError) as e:
                        log.warning(
                            "hybrid group /%s slash failed (%s), prefix-only", gname, e
                        )
                        nested = _orig_group(*args, **{**kw, "with_app_command": False})(
                            sub_prepared
                        )
                    _apply_aliases(nested, sub_aliases)
                    nested.example = sub_example
                    nested.parameters = sub_params

                    _nested_orig_command = nested.command

                    def nested_command(*n_args: Any, **n_kw: Any):
                        n_example = n_kw.pop("example", None)
                        n_params = n_kw.pop("parameters", {})
                        n_guild_only = n_kw.pop("guild_only", False)
                        n_servers = n_kw.pop("guilds", None)
                        n_dms = n_kw.pop("dms", None)
                        n_gcs = n_kw.pop("groupchats", None)
                        if not n_kw.pop("slash", True):
                            n_kw["with_app_command"] = False
                        n_kw.pop("dm_enabled", None)
                        n_kw.pop("cls", None)
                        n_aliases_raw = n_kw.pop("aliases", None)
                        n_aliases = (
                            None
                            if n_aliases_raw is None
                            else _normalize_aliases(n_aliases_raw)
                        )
                        if n_aliases is not None:
                            n_kw["aliases"] = list(n_aliases)
                        ng, nd, nc = _resolve_contexts(
                            guild_only=n_guild_only,
                            guilds=n_servers,
                            dms=n_dms,
                            groupchats=n_gcs,
                        )

                        def nested_deco(n_fn):
                            n_prepared = _inject_descriptions(
                                _wrap_callback(n_fn, guilds=ng, dms=nd, groupchats=nc),
                                n_params,
                            )
                            try:
                                cmd = _nested_orig_command(*n_args, **n_kw)(n_prepared)
                            except (TypeError, ValueError):
                                cmd = _nested_orig_command(
                                    *n_args, **{**n_kw, "with_app_command": False}
                                )(n_prepared)
                            _apply_aliases(cmd, n_aliases)
                            cmd.example = n_example
                            cmd.parameters = n_params
                            return cmd

                        return nested_deco

                    nested.command = nested_command
                    return nested

                return sub_deco

            grp.group = sub_group  # type: ignore[method-assign]
            grp._hybrid_group_override = sub_group

        return grp

    return deco


def slash_hybrid(name: str | None = None, **attrs: Any):
    """slash-only command: no prefix registration, added in cog_load."""
    description = attrs.get("description")
    example, params, guild_only, guilds, dms, groupchats, _, _, _ = _pop_hybrid_attrs(attrs)
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
    skip = {"self", "cls", "ctx", "context", "interaction"}
    for param_name in list(inspect.signature(method).parameters)[2:]:
        if param_name.lower() in skip:
            continue
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
