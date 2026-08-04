"""role converter with fuzzy name matching and dangerous permission helpers."""

from __future__ import annotations

from discord.ext.commands import Converter, CommandError, Context, RoleNotFound
from discord.utils import find
import discord

try:
    from fast_string_match import closest_match
except ImportError:
    def closest_match(query, candidates):
        return None

from re import compile

DISCORD_ID = compile(r"^[0-9]{17,}$")
DISCORD_ROLE_MENTION = compile(r"<@&(\d+)>")

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


class RoleConvert(Converter):
    """convert string to guild Role"""

    async def convert(self, ctx: Context, arg: str) -> discord.Role:
        role = None
        if match := DISCORD_ID.match(arg):
            role = ctx.guild.get_role(int(match.group(0)))
        elif match := DISCORD_ROLE_MENTION.match(arg):
            role = ctx.guild.get_role(int(match.group(1)))
        else:
            try:
                role_id = int(arg.strip("<@&>"))
                role = ctx.guild.get_role(role_id)
            except Exception:
                pass
            if role is None:
                arg_low = arg.lower()
                role = (
                    find(lambda r: r.name.lower() == arg_low, ctx.guild.roles)
                    or find(lambda r: arg_low in r.name.lower(), ctx.guild.roles)
                    or find(lambda r: r.name.lower().startswith(arg_low), ctx.guild.roles)
                )
                if role is None:
                    names = [r.name for r in ctx.guild.roles]
                    if match := closest_match(arg, names):
                        role = discord.utils.get(ctx.guild.roles, name=match)

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


# Backwards-compatible alias used by some command signatures
Role = RoleConvert
