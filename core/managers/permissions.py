from __future__ import annotations

import json
import re

from discord.ext import commands
from discord.ext.commands import CommandError, MissingPermissions


_SPECIAL_PERMISSIONS = {"guild_owner", "server_owner"}


async def _fake_permissions(ctx) -> set[str]:
    role_ids = [role.id for role in getattr(ctx.author, "roles", ())]
    if not role_ids:
        return set()

    try:
        rows = await ctx.bot.db.fetch(
            """SELECT permissions FROM fake_permissions
               WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])""",
            ctx.guild.id,
            role_ids,
        )
    except Exception:
        return set()

    collected: set[str] = set()
    for row in rows:
        raw = row[0] if isinstance(row, tuple) else getattr(row, "permissions", None)
        if raw is None:
            continue
        if isinstance(raw, str):
            try:
                values = json.loads(raw)
            except json.JSONDecodeError:
                values = [piece for piece in re.split(r"[\s,]+", raw) if piece]
        else:
            values = list(raw)
        collected.update(str(value).lower() for value in values)
    return collected


def has_permissions(**permissions):
    required = dict(permissions)

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")

        if await ctx.bot.is_owner(ctx.author):
            return True

        if ctx.author.id == ctx.guild.owner_id:
            return True

        owner_required = any(required.get(name) for name in _SPECIAL_PERMISSIONS)
        missing = []
        if owner_required and ctx.author.id != ctx.guild.owner_id:
            missing.append("guild owner")

        guild_permissions = ctx.author.guild_permissions
        for name, enabled in required.items():
            if not enabled or name in _SPECIAL_PERMISSIONS:
                continue
            if not getattr(guild_permissions, name, False):
                missing.append(name)

        if not missing:
            return True

        fake_permissions = await _fake_permissions(ctx)
        if "administrator" in fake_permissions:
            return True

        unresolved = []
        for name in missing:
            lookup = name.replace(" ", "_")
            if lookup in ("server_owner", "guild_owner"):
                if ctx.author.id == ctx.guild.owner_id:
                    continue
            elif lookup in fake_permissions:
                continue
            else:
                unresolved.append(name)

        if not unresolved:
            return True

        if unresolved == ["guild owner"]:
            raise CommandError(
                f"You must be the **guild owner** to run this command."
            )

        raise MissingPermissions([name.replace(" ", "_") for name in unresolved])

    return commands.check(predicate)
