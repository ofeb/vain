from __future__ import annotations

from abc import ABC

from discord.ext import commands


class _Meta(type(commands.Cog), type(ABC)):
    """metaclass merging cog and abc types"""
    pass


class Mixin(commands.Cog, ABC, metaclass=_Meta):
    """base class for multi-file cog mixins.
    inherit from this in each mixin file.
    lets you split one cog across multiple files"""
    pass
