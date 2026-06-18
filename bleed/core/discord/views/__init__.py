"""discord ui view components.
each file is a reusable view for commands.
from core.discord.views import EmbedView ConfirmView"""

from .embed import EmbedView
from .confirm import ConfirmView
from .roles import RoleSelectView
from .paginate import PaginateView

__all__ = ["EmbedView", "ConfirmView", "RoleSelectView", "PaginateView"]
