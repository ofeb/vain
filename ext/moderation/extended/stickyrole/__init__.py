from __future__ import annotations

import contextlib

import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.tools.hierarchy import ensure_member_hierarchy
from discord.ext.commands import CommandError
from core.discord.views.embed import panel_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class Stickyrole(Package):
    """Reapply roles to members when they rejoin."""

    @group(
        name="stickyrole",
        aliases=["stickyroles", "srole"],
        description="Reapplies a role on join",
        invoke_without_command=True,
        example=",stickyrole add @member @Role",
    )
    @has_permissions(manage_roles=True)
    async def stickyrole(self, ctx):
        """stickyrole group help"""
        return await ctx.send_help(ctx.command)

    @stickyrole.command(
        name="add",
        aliases=["set", "create"],
        description="Reapplies a role on join",
        example=",stickyrole add @member @Role",
    )
    @has_permissions(manage_roles=True)
    async def stickyrole_add(self, ctx, member: discord.Member, role: discord.Role):
        """add sticky role for a member"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")

        try:
            await ensure_member_hierarchy(ctx, member, allow_self=True)
        except CommandError as e:
            return await ctx.warn(str(e))

        if role >= ctx.guild.me.top_role:
            return await ctx.warn("That role is **higher** than my top role")
        if role.is_default() or role.managed:
            return await ctx.warn("Cannot sticky the default or managed roles")

        existing = await self.db.fetchval(
            "SELECT 1 FROM sticky_roles WHERE guild_id = $1 AND user_id = $2 AND role_id = $3",
            ctx.guild.id,
            member.id,
            role.id,
        )
        if existing:
            return await ctx.warn(f"{role.mention} is already sticky for **{member}**")

        await self.db.execute(
            """INSERT INTO sticky_roles (guild_id, user_id, role_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, user_id, role_id) DO NOTHING""",
            ctx.guild.id,
            member.id,
            role.id,
        )

        if role not in member.roles:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await member.add_roles(role, reason=f"stickyrole add by {ctx.author}")

        return await ctx.success(
            f"Sticky role {role.mention} set for **{member}** (reapplied on join)"
        )

    @stickyrole.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="Removes sticky role on join",
        example=",stickyrole remove @member @Role",
    )
    @has_permissions(manage_roles=True)
    async def stickyrole_remove(self, ctx, member: discord.Member, role: discord.Role):
        """remove sticky role for a member"""
        result = await self.db.execute(
            "DELETE FROM sticky_roles WHERE guild_id = $1 AND user_id = $2 AND role_id = $3",
            ctx.guild.id,
            member.id,
            role.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"{role.mention} is not sticky for **{member}**")
        return await ctx.success(f"Removed sticky role {role.mention} from **{member}**")

    @stickyrole.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of every sticky role",
    )
    @has_permissions(manage_roles=True)
    async def stickyrole_list(self, ctx, member: discord.Member | None = None):
        """list sticky roles (optionally for one member)"""
        if member:
            rows = await self.db.fetch(
                "SELECT role_id FROM sticky_roles WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                member.id,
            )
            if not rows:
                return await ctx.warn(f"**{member}** has no sticky roles")
            lines = []
            for row in rows:
                role = ctx.guild.get_role(row["role_id"])
                lines.append(role.mention if role else f"`{row['role_id']}`")
            embed = panel_embed(
                title=f"Sticky Roles - {member}",
                color=None,
                lines=lines,
                timestamp=False,
            )
            return await ctx.send(embed=embed)

        rows = await self.db.fetch(
            "SELECT user_id, role_id FROM sticky_roles WHERE guild_id = $1 ORDER BY user_id",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No sticky roles are set")

        lines = []
        for row in rows[:40]:
            member_obj = ctx.guild.get_member(row["user_id"])
            who = member_obj.mention if member_obj else f"`{row['user_id']}`"
            role = ctx.guild.get_role(row["role_id"])
            role_label = role.mention if role else f"`{row['role_id']}`"
            lines.append(label_line(who, role_label))

        embed = panel_embed(
            title=f"Sticky Roles ({len(rows)})",
            color=None,
            lines=lines,
            footer=f"{len(rows)} total" if len(rows) > 40 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @stickyrole.command(
        name="clear",
        description="Clear all sticky roles for a member or the whole server",
        example=",stickyrole clear @member",
    )
    @has_permissions(manage_roles=True)
    async def stickyrole_clear(self, ctx, member: discord.Member | None = None):
        """clear sticky roles"""
        if member:
            result = await self.db.execute(
                "DELETE FROM sticky_roles WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                member.id,
            )
            if result == "DELETE 0":
                return await ctx.warn(f"**{member}** has no sticky roles")
            return await ctx.success(f"Cleared sticky roles for **{member}**")

        result = await self.db.execute(
            "DELETE FROM sticky_roles WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success(f"Cleared all sticky roles ({result})")
