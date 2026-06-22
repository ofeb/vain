"""argument converters for discord.py commands.
each file handles one discord object type.
from core.tools.convert import MemberConvert RoleConvert"""

from .member import MemberConvert, OptionalGameMember
from .role import RoleConvert
from .channel import ChannelConvert
from .color import ColorConvert
from .status import StatusConvert

__all__ = ["MemberConvert", "OptionalGameMember", "RoleConvert", "ChannelConvert", "ColorConvert", "StatusConvert"]
