from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands, tasks

from .mixin import Mixin

if TYPE_CHECKING:
    from core.bleed import Bleed
    from core.managers.database.client import Database
    from core.managers.redis import RedisClient
    from core.managers.guard import Guard


class Package(Mixin):
    """base class every ext cog inherits from.
    provides shortcuts to bot db redis and guard.
    inherit this in both commands and events files"""

    listener = staticmethod(commands.Cog.listener)

    def __init__(self, bot: Bleed) -> None:
        self.bot = bot

    @property
    def db(self) -> Database:
        return self.bot.db

    @property
    def redis(self) -> RedisClient | None:
        return self.bot.redis

    @property
    def guard(self) -> Guard:
        return self.bot.guard

    @property
    def color(self) -> int:
        return self.bot.color

    async def create_embed(self, template: str, **kw):
        return await self.bot.create_embed(template, **kw)
