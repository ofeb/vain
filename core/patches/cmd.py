from __future__ import annotations

import inspect
from typing import Any

import discord
from discord.ext.commands import Command, Context
from discord.ext.commands.core import hooked_wrapped_callback

_ORIG_COMMAND_INIT = Command.__init__
_CTX_PARAM_NAMES = frozenset({"ctx", "context", "interaction", "inter"})


def _is_context_like(obj: Any) -> bool:
    if obj is None or obj is inspect.Parameter.empty:
        return False
    try:
        for cls in (Context, discord.Interaction):
            if inspect.isclass(obj) and issubclass(obj, cls):
                return True
    except TypeError:
        pass
    name = getattr(obj, "__name__", "") or str(obj)
    low = name.lower()
    return low in {"context", "interaction"} or low.endswith(".context") or low.endswith(".interaction")


def drop_injected_context_params(cmd: Command) -> None:
    """Remove framework-injected context params from ``cmd.params``.

    discord.py already puts ``[cog, ctx]`` into ``ctx.args`` before converting
    user parameters. If ``ctx`` remains in ``params`` (common with nested
    wrappers / dynamic command factories), dpy tries to *convert* a message
    token into ``Context`` and blows up.
    """
    params = getattr(cmd, "params", None)
    if not isinstance(params, dict) or not params:
        return

    drop: list[str] = []
    for name, param in list(params.items()):
        key = name.lower()
        if key in _CTX_PARAM_NAMES:
            drop.append(name)
            continue
        converter = getattr(param, "converter", None)
        annotation = getattr(param, "annotation", None)
        if _is_context_like(converter) or _is_context_like(annotation):
            drop.append(name)

    for name in drop:
        params.pop(name, None)


def _patched_command_init(self, func, **kwargs) -> None:
    
    example = kwargs.pop("example", None)
    parameters = kwargs.pop("parameters", None)
    _ORIG_COMMAND_INIT(self, func, **kwargs)
    if example is not None:
        self.example = example
    elif not hasattr(self, "example"):
        self.example = None
    if parameters is not None:
        self.parameters = parameters
    elif not hasattr(self, "parameters"):
        self.parameters = {}
    drop_injected_context_params(self)



Command.__init__ = _patched_command_init  # type: ignore[method-assign]


class PatchedCommand(Command):
    """command with flag kwarg stripping support"""

    async def invoke(self, ctx, /) -> None:
        
        drop_injected_context_params(self)
        await self.prepare(ctx)

        if ctx.kwargs and (FlagConv := getattr(ctx.command, "flags", None)):
            kwarg = list(ctx.kwargs.keys())[-1]
            arg = list(ctx.kwargs.values())[-1]
            from core.tools.models import ScriptType

            if arg is None or isinstance(arg, (str, ScriptType)):
                raw = "" if arg is None else str(arg)
                parsed = await FlagConv.convert(ctx, raw.replace("-", "--"))
                cleaned = raw.replace("-", "--")
                for name, value in parsed:
                    ctx.flags[name] = value
                    names = [name]
                    if aliases := parsed.get_flags()[name].aliases:
                        names.extend(aliases)
                    for n in names:
                        cleaned = (
                            cleaned.replace(f"--{n} {value}", "")
                            .replace(f"--{n}", "")
                            .strip()
                        )

                default = getattr(ctx.command.params.get(kwarg), "default", None)
                if cleaned:
                    ctx.kwargs[kwarg] = ScriptType(cleaned)
                elif isinstance(default, str):
                    ctx.kwargs[kwarg] = ScriptType(default)
                else:
                    ctx.kwargs[kwarg] = None

        ctx.invoked_subcommand = None
        ctx.subcommand_passed = None
        await hooked_wrapped_callback(self, ctx, self.callback)(*ctx.args, **ctx.kwargs)


Command.invoke = PatchedCommand.invoke
