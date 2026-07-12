from __future__ import annotations

from core.discord.mixin import _Meta
from core.discord.package import Package

from .roleplay import RoleplayCommands
from .events import RoleplayEvents


if __name__ == "__main__":
    pass


class Roleplay(
    RoleplayCommands,
    RoleplayEvents,
    Package,
    metaclass=_Meta,
):
    def __init__(self, bot):
        Package.__init__(self, bot)


async def setup(bot):
    await bot.add_cog(Roleplay(bot))
