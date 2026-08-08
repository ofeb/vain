"""role converter with smart name matching and dangerous permission helpers."""

from __future__ import annotations

import re

import discord
from discord.ext.commands import CommandError, Context, Converter, RoleNotFound

from .regex import clean_query, regex_find

DISCORD_ID = re.compile(r"^[0-9]{15,22}$")
DISCORD_ROLE_MENTION = re.compile(r"<@&(\d{15,22})>")

DANGEROUS_PERMISSIONS = [
    "administrator",
    "kick_members",
    "ban_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_expressions",
    "manage_webhooks",
    "manage_nicknames",
    "mention_everyone",
]


def _role_names(role: discord.Role) -> list[str | None]:
    return [role.name]


class RoleConvert(Converter):
    """Convert string to guild Role.

    Accepts mentions, IDs, exact names, and smart partials:
    ``own`` → ``ʚ .  own``, ``boost`` → ``・boost・``, etc.
    """

    async def convert(self, ctx: Context, arg: str) -> discord.Role:
        if ctx.guild is None:
            raise RoleNotFound(arg)

        raw = clean_query(arg)
        if not raw:
            raise RoleNotFound(arg)

        role: discord.Role | None = None

        if match := DISCORD_ID.match(raw):
            role = ctx.guild.get_role(int(match.group(0)))
        elif match := DISCORD_ROLE_MENTION.match(str(arg).strip()):
            role = ctx.guild.get_role(int(match.group(1)))
        else:
            
            try:
                role_id = int(str(arg).strip().strip("<@&>"))
                if 15 <= len(str(role_id)) <= 22:
                    role = ctx.guild.get_role(role_id)
            except Exception:
                role = None

        if role is None:
            
            candidates = [r for r in ctx.guild.roles if not r.is_default()]
            role = regex_find(raw, candidates, names_of=_role_names, fuzzy=True)

        if not role or role.is_default():
            raise RoleNotFound(arg)
        return role

    @staticmethod
    async def manageable(ctx: Context, role: discord.Role, booster: bool = False) -> bool:
        if role.managed and not booster:
            raise CommandError(f"You're unable to manage {role.mention}")
        if not role.is_assignable() and not booster:
            raise CommandError(f"I'm unable to manage {role.mention}")
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            raise CommandError(f"You're unable to manage {role.mention}")
        return True

    @staticmethod
    async def dangerous(ctx: Context, role: discord.Role, action: str = "manage") -> bool:
        permissions = [
            perm
            for perm in DANGEROUS_PERMISSIONS
            if getattr(role.permissions, perm, False)
        ]
        if permissions and ctx.author.id != ctx.guild.owner_id:
            raise CommandError(
                f"You're unable to {action} {role.mention} because it has the `{permissions[0]}` permission"
            )
        return False


Role = RoleConvert
