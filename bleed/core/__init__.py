"""core runtime initialization.

Load command/runtime compatibility patches before any extension modules import
decorators or converter aliases from discord.py.
"""

from .compat import commands as _commands_compat  # noqa: F401
from .patches import cmd as _command_patch  # noqa: F401
