"""argument converters for discord.py commands.
each file handles one discord object type.
from core.tools.convert import MemberConvert RoleConvert"""

from .member import MemberConvert, OptionalMember
from .role import RoleConvert
from .channel import ChannelConvert
from .color import ColorConvert
from .status import StatusConvert

__all__ = ["MemberConvert", "OptionalMember", "RoleConvert", "ChannelConvert", "ColorConvert", "StatusConvert"]
