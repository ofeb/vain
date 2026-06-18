"""discord object monkey patches.
applies patches to Message User and Channel classes.
import this module early to activate all patches"""

from . import msg, user, channel

__all__ = ["msg", "user", "channel"]
