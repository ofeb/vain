"""argument converters for discord.py commands.
each file handles one discord object type.
from core.tools.convert import MemberConvert RoleConvert"""

from .member import MemberConvert
from .role import RoleConvert
from .channel import (
    ChannelConvert,
    TextChannelConvert,
    resolve_channel,
    clean_channel_token,
    patch_discord_channel_converters,
)
from .color import ColorConvert
from .status import StatusConvert

__all__ = [
    "MemberConvert",
    "RoleConvert",
    "ChannelConvert",
    "TextChannelConvert",
    "ColorConvert",
    "StatusConvert",
    "resolve_channel",
    "clean_channel_token",
    "patch_discord_channel_converters",
]
