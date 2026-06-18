"""patched context base class.
extends commands.Context with bot specific helpers.
use this as the bot context_class"""

from discord.ext.commands import Context as _Ctx
from .reply import success, fail, warn


class PatchedContext(_Ctx):
    """context with send reply helpers"""

    flags: dict = {}

    async def success(self, msg: str, **kw):
        return await success(self, msg, **kw)

    async def fail(self, msg: str, **kw):
        return await fail(self, msg, **kw)

    async def warn(self, msg: str, **kw):
        return await warn(self, msg, **kw)
