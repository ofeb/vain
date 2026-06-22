from __future__ import annotations

from discord.ext import commands

from core.discord.mixin import _Meta

from .information import InformationCommands
from .extended.sticker.sticker import Sticker
from .extended.emoji.emoji import Emoji
from .extended.highlight.highlight import Highlight
from .extended.birthday.birthday import Birthday
from .extended.timezone.timezone import Timezone
from .extended.roblox.roblox import Roblox
from .extended.snapchat.snapchat import Snapchat


class Information(
    InformationCommands,
    Sticker,
    Emoji,
    Highlight,
    Birthday,
    Timezone,
    Roblox,
    Snapchat,
    commands.Cog,
    metaclass=_Meta,
):
    """main information extension — all subcommands combined"""


async def setup(bot) -> None:
    """load information extension"""
    from .events import InformationEvents

    await bot.add_cog(Information(bot))
    await bot.add_cog(InformationEvents(bot))
