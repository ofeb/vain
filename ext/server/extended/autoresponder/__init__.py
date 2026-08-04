from __future__ import annotations

from .core import AutoresponderCore
from .commands import AutoresponderCommandMixin


class AutoresponderCommands(AutoresponderCommandMixin, AutoresponderCore):
    """Autoresponder setup and management."""
    pass


__all__ = ["AutoresponderCommands"]
