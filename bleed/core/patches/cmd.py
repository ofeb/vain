"""patches discord.py Command invoke method.
adds flag parsing support to standard commands.
automatically strips flag tokens from kwargs"""

from discord.ext.commands import Command
from discord.ext.commands.core import hooked_wrapped_callback
from loguru import logger


class PatchedCommand(Command):
    """command with flag kwarg stripping support"""

    async def invoke(self, ctx, /) -> None:
        try:
            await self.prepare(ctx)
        except Exception as e:
            raise e

        if ctx.kwargs and (FlagConv := getattr(ctx.command, "flags", None)):
            kwarg = list(ctx.kwargs.keys())[-1]
            arg = list(ctx.kwargs.values())[-1]
            from core.tools.models import ScriptType

            if arg is None or isinstance(arg, (str, ScriptType)):
                parsed = await FlagConv.convert(ctx, str(arg).replace("—", ""))
                for name, value in parsed:
                    ctx.flags[name] = value
                    names = [name]
                    if aliases := parsed.get_flags()[name].aliases:
                        names.extend(aliases)
                    for n in names:
                        if isinstance(arg, str):
                            ctx.kwargs[kwarg] = (
                                str(ctx.kwargs.get(kwarg))
                                .replace("—", "--")
                                .replace(f"--{n} {value}", "")
                                .replace(f"--{n}", "")
                                .strip()
                            ) or (
                                ctx.command.params.get(kwarg).default
                                if isinstance(ctx.command.params.get(kwarg).default, str)
                                else None
                            )
                        elif isinstance(arg, ScriptType):
                            arg.script = (
                                arg.script.replace("—", "--")
                                .replace(f"--{n} {value}", "")
                                .replace(f"--{n}", "")
                                .strip()
                            )
                            ctx.kwargs[kwarg] = arg or (
                                ctx.command.params.get(kwarg).default
                                if isinstance(ctx.command.params.get(kwarg).default, str)
                                else None
                            )

        ctx.invoked_subcommand = None
        ctx.subcommand_passed = None
        await hooked_wrapped_callback(self, ctx, self.callback)(*ctx.args, **ctx.kwargs)


Command.invoke = PatchedCommand.invoke
