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


class Forcenickname(Package):
    """Force and lock a member's nickname."""

    @group(
        name="forcenickname",
        aliases=["forcenick", "fn"],
        description="Force a member's nickname and keep it locked",
        invoke_without_command=True,
        example=",forcenickname @member cool name",
    )
    @has_permissions(manage_nicknames=True)
    async def forcenickname(
        self,
        ctx,
        member: discord.Member,
        *,
        name_to_set: str,
    ):
        """Force and lock a nickname for a member."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")

        try:
            await ensure_member_hierarchy(ctx, member, allow_self=False)
        except CommandError as e:
            return await ctx.warn(str(e))

        nick = name_to_set.strip()[:32]
        if not nick:
            return await ctx.warn("Provide a nickname to force")

        try:
            await member.edit(nick=nick, reason=f"forcenickname by {ctx.author}")
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to change that member's nickname")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to set nickname: {e}")

        await self.db.execute(
            """INSERT INTO forced_nicknames (guild_id, user_id, nickname)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, user_id)
               DO UPDATE SET nickname = excluded.nickname""",
            ctx.guild.id,
            member.id,
            nick,
        )
        return await ctx.success(
            f"Forced nickname for **{member}** to **{nick}** (locked until removed)"
        )

    @forcenickname.command(
        name="list",
        aliases=["ls", "show"],
        description="View all forced nicknames in this server",
    )
    @has_permissions(manage_guild=True)
    async def forcenickname_list(self, ctx):
        """List forced nicknames."""
        rows = await self.db.fetch(
            "SELECT user_id, nickname FROM forced_nicknames WHERE guild_id = $1 ORDER BY nickname",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No forced nicknames are set")

        lines = []
        for row in rows[:40]:
            member = ctx.guild.get_member(row["user_id"])
            who = member.mention if member else f"`{row['user_id']}`"
            lines.append(label_line(who, f"`{row['nickname']}`"))

        embed = panel_embed(
            title=f"Forced Nicknames ({len(rows)})",
            color=self.color,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @forcenickname.command(
        name="remove",
        aliases=["delete", "del", "clear"],
        description="Remove a forced nickname lock",
        example=",forcenickname remove @member",
    )
    @has_permissions(manage_nicknames=True)
    async def forcenickname_remove(self, ctx, member: discord.Member):
        """Remove forced nickname for a member."""
        result = await self.db.execute(
            "DELETE FROM forced_nicknames WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            member.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"**{member}** does not have a forced nickname")

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await member.edit(nick=None, reason=f"forcenickname remove by {ctx.author}")

        return await ctx.success(f"Removed forced nickname for **{member}**")
