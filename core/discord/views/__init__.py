"""discord ui view components.
each file is a reusable view for commands.
from core.discord.views import EmbedView ConfirmView"""

from .embed import EmbedView
from .confirm import ConfirmView
from .roles import RoleSelectView
from .paginate import PaginateView, needs_pagination, send_pages
from .rolepages import (
    build_inrole_pages,
    build_roleinfo_pages,
    build_roles_pages,
    role_color_parts,
    role_icon_url,
)

__all__ = [
    "EmbedView",
    "ConfirmView",
    "RoleSelectView",
    "PaginateView",
    "send_pages",
    "needs_pagination",
    "build_roles_pages",
    "build_roleinfo_pages",
    "build_inrole_pages",
    "role_color_parts",
    "role_icon_url",
]
