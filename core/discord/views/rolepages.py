from __future__ import annotations

import math
from typing import Iterable

import discord
from discord import ui

from core.discord.views.embed import body

_PAGE_SIZE = 10


def _ts(dt) -> str:
    return f"<t:{int(dt.timestamp())}:R>"


def role_color_parts(role: discord.Role) -> tuple[str | None, str | None]:
    """Resolve a role's colour display.

    Returns ``(label, value)`` where gradient roles show both colours,
    holographic roles show no colour value, default roles are labelled
    ``Default``, and solid roles just show their hex value.
    """
    secondary = role.secondary_colour
    tertiary = role.tertiary_colour
    if secondary is not None:
        return "Gradient", f"`#{role.colour.value:06x}` → `#{secondary.value:06x}`"
    if tertiary is not None:
        return "Holographic", None
    value = role.colour.value
    if value == 0:
        return "Default", "`#000000`"
    return None, f"`#{value:06x}`"


def role_icon_url(role: discord.Role) -> str | None:
    """CDN url for a role's custom icon, or None (unicode emoji has no url)."""
    icon = role.display_icon
    if isinstance(icon, discord.Asset):
        return icon.url
    return None


def _sort_members(members: Iterable[discord.Member]) -> list[discord.Member]:
    return sorted(
        members,
        key=lambda m: (m.joined_at is None, m.joined_at or m.created_at),
    )


def _member_since(member: discord.Member) -> str:
    return _ts(member.joined_at or member.created_at)


def _member_line(index: int, member: discord.Member) -> str:
    return (
        f"-# `{index}.` **{member.display_name}**"
        f" • held since at least {_member_since(member)}"
    )


def _role_line(index: int, role: discord.Role) -> str:
    return f"-# `{index}.` {role.mention} - **Created** {_ts(role.created_at)}"


def build_roles_pages(
    guild: discord.Guild,
    roles: Iterable[discord.Role],
    *,
    page_size: int = _PAGE_SIZE,
) -> list[ui.Container]:
    """Numbered role listing, ``page_size`` roles per page."""
    roles = list(roles)
    if not roles:
        container = ui.Container()
        container.add_item(ui.TextDisplay("-# no roles to show"))
        return [container]

    total_pages = max(1, math.ceil(len(roles) / page_size))
    pages: list[ui.Container] = []
    for page_number, start in enumerate(
        range(0, len(roles), page_size), start=1
    ):
        chunk = roles[start : start + page_size]
        container = ui.Container()
        container.add_item(ui.TextDisplay(f"**Roles in {guild.name}**"))
        container.add_item(
            ui.TextDisplay(
                f"-# Role count · {len(roles)} · Page {page_number}/{total_pages}"
            )
        )
        container.add_item(ui.Separator(visible=True))
        container.add_item(
            ui.TextDisplay(
                body(
                    *[
                        _role_line(i, role)
                        for i, role in enumerate(chunk, start=start + 1)
                    ]
                )
            )
        )
        pages.append(container)
    return pages


def build_inrole_pages(
    role: discord.Role,
    members: Iterable[discord.Member],
    *,
    page_size: int = _PAGE_SIZE,
) -> list[ui.Container]:
    """Numbered member listing for a role, ``page_size`` members per page."""
    members = _sort_members(members)
    if not members:
        container = ui.Container()
        container.add_item(ui.TextDisplay("-# no members to show"))
        return [container]

    total_pages = max(1, math.ceil(len(members) / page_size))
    pages: list[ui.Container] = []
    for page_number, start in enumerate(
        range(0, len(members), page_size), start=1
    ):
        chunk = members[start : start + page_size]
        container = ui.Container()
        container.add_item(ui.TextDisplay(f"**Members with {role.mention}**"))
        container.add_item(
            ui.TextDisplay(
                f"-# {len(members)} total · Page {page_number}/{total_pages}"
            )
        )
        container.add_item(ui.Separator(visible=True))
        container.add_item(
            ui.TextDisplay(
                body(
                    *[
                        _member_line(i, member)
                        for i, member in enumerate(chunk, start=start + 1)
                    ]
                )
            )
        )
        pages.append(container)
    return pages


def build_roleinfo_pages(
    role: discord.Role,
    *,
    page_size: int = _PAGE_SIZE,
) -> list[ui.Container]:
    """Role info page plus additional member pages when the role has many."""
    members = _sort_members(role.members)
    total = len(members)
    total_member_pages = max(1, math.ceil(total / page_size))

    pages: list[ui.Container] = [build_roleinfo_container(role, members)]

    for page_number, start in enumerate(
        range(page_size, total, page_size), start=2
    ):
        chunk = members[start : start + page_size]
        container = ui.Container()
        container.add_item(ui.TextDisplay(f"**Members with {role.mention}**"))
        container.add_item(
            ui.TextDisplay(
                f"-# {total} total · Page {page_number}/{total_member_pages}"
            )
        )
        container.add_item(ui.Separator(visible=True))
        container.add_item(
            ui.TextDisplay(
                body(
                    *[
                        _member_line(i, member)
                        for i, member in enumerate(chunk, start=start + 1)
                    ]
                )
            )
        )
        pages.append(container)
    return pages


def build_roleinfo_container(
    role: discord.Role,
    members: list[discord.Member],
    *,
    page_size: int = _PAGE_SIZE,
) -> ui.Container:
    """Single role info container: information, details and first members."""
    guild_name = role.guild.name if role.guild else "this server"
    total = len(members)
    head = members[:page_size]

    container = ui.Container()
    container.add_item(ui.TextDisplay(f"**{role.name}**"))
    container.add_item(ui.TextDisplay(f"-# {guild_name} · {role.mention}"))
    container.add_item(ui.Separator(visible=True))

    container.add_item(ui.TextDisplay("**Information**"))
    container.add_item(
        ui.TextDisplay(
            body(
                f"{role.mention} · `{role.id}`",
                f"Created {_ts(role.created_at)}",
                f"`{total}` members",
            )
        )
    )

    label, value = role_color_parts(role)
    if label and value:
        color_line = f"Color: **{label}** {value}"
    elif label:
        color_line = f"Color: **{label}**"
    elif value:
        color_line = f"Color: {value}"
    else:
        color_line = "Color: `#000000`"

    detail_lines = [color_line]
    icon_url = role_icon_url(role)
    if icon_url:
        detail_lines.append(f"Icon: [click me]({icon_url})")
    detail_lines.extend(
        [
            f"Position: `{role.position}`",
            f"Hoisted: {'Yes' if role.hoist else 'No'}",
            f"Mentionable: {'Yes' if role.mentionable else 'No'}",
            f"Managed: {'Yes' if role.managed else 'No'}",
        ]
    )
    container.add_item(ui.TextDisplay("**Details**"))
    container.add_item(ui.TextDisplay(body(*detail_lines)))

    container.add_item(ui.Separator(visible=True))
    container.add_item(ui.TextDisplay(f"**Members ({total})**"))
    if head:
        container.add_item(
            ui.TextDisplay(
                body(*[_member_line(i, m) for i, m in enumerate(head, start=1)])
            )
        )
    else:
        container.add_item(ui.TextDisplay(body("-# No members")))
    return container
