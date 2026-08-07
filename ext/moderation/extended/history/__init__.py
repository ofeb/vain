from __future__ import annotations

import discord
from discord.ext.commands import CommandError, group

from core.discord.package import Package
from core.managers.permissions import has_permissions

from core.discord.views.embed import panel_embed

def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"

class History(Package):
    """history management"""

    def _format_case_line(self, row) -> str:
        target = f"`{row['target_id']}`" if row.get("target_id") else "unknown"
        moderator = f"`{row['moderator_id']}`" if row.get("moderator_id") else "unknown"
        reason = row.get("reason") or "no reason provided"
        return label_line(
            f"Case #{row['case_id']} · {row['action']}",
            f"{target} · {moderator} · {reason}",
        )

    @group(
        name="history",
        description="View a list of every punishment recorded",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def history(self, ctx, member: discord.Member, command: str | None = None):
        """view history"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        rows = await self.db.fetch_modlog_cases_for_user(
            ctx.guild.id,
            member.id,
            action=command.lower() if command else None,
            limit=25,
        )
        if not rows:
            return await ctx.warn(f"{member.mention} has **no punishment history**")
        title = f"History — {member}"
        if command:
            title += f" ({command})"
        embed = panel_embed(
            title=title,
            color=None,
            lines=[self._format_case_line(row) for row in rows],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @history.command(
        name="view",
        description="View an ID's case log",
    )
    @has_permissions(manage_messages=True)
    async def history_view(self, ctx, case_id: int):
        """view case log"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        row = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not row:
            return await ctx.warn(f"Case **#{case_id}** was not found")
        target = ctx.guild.get_member(row["target_id"])
        target_label = target.mention if target else f"`{row['target_id']}`"
        moderator = ctx.guild.get_member(row["moderator_id"])
        moderator_label = moderator.mention if moderator else f"`{row['moderator_id']}`"
        from core.tools.moderation_logs import build_modlog_embed

        embed = build_modlog_embed(
            color=None,
            action=str(row["action"]),
            target_label=target_label,
            moderator_label=moderator_label,
            reason=row.get("reason") or "no reason provided",
            case_id=row["case_id"],
        )
        await ctx.send(embed=embed)

    @history.command(
        name="remove",
        description="Remove a punishment from a member",
    )
    @has_permissions(manage_messages=True)
    async def history_remove(self, ctx, member: discord.Member, case_id: int):
        """remove punishment"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        row = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not row or row["target_id"] != member.id:
            raise CommandError(f"case **#{case_id}** was not found for {member.mention}")
        await self.db.execute(
            "DELETE FROM modlog_cases WHERE guild_id = $1 AND case_id = $2",
            ctx.guild.id,
            case_id,
        )
        return await ctx.success(f"Removed case **#{case_id}** for {member.mention}")

    @history.command(
        name="removeall",
        description="Remove all punishments from a member",
    )
    @has_permissions(administrator=True)
    async def history_removeall(self, ctx, member: discord.Member):
        """remove all punishments"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        result = await self.db.execute(
            "DELETE FROM modlog_cases WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id,
            member.id,
        )
        return await ctx.success(f"Cleared punishment history for {member.mention} ({result})")
