from __future__ import annotations

import re
import discord
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.discord.hybrid import hybrid, describe
from core.managers.permissions import has_permissions

from core.discord.views.embed import panel_embed

_ID_RE = re.compile(r"^\d{15,20}$")

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

    async def _resolve_user_id(self, ctx, target: str) -> int:
        """Resolve a user ID from a mention, user object, or raw ID string."""
        raw = target.strip()
        mention_match = re.match(r"<@!?(\d+)>", raw)
        if mention_match:
            return int(mention_match.group(1))
        if _ID_RE.match(raw):
            return int(raw)
        try:
            user = await commands.UserConverter().convert(ctx, raw)
            return user.id
        except CommandError:
            raise CommandError(f"could not find a user matching `{target}`")

    @hybrid(
        name="history",
        description="View a list of every punishment recorded",
        group=True,
    )
    @has_permissions(manage_messages=True)
    @describe(target="User ID, mention, or username to check", command="Filter by action type")
    async def history(self, ctx, target: str, command: str | None = None):
        """view history"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        user_id = await self._resolve_user_id(ctx, target)
        rows = await self.db.fetch_modlog_cases_for_user(
            ctx.guild.id,
            user_id,
            action=command.lower() if command else None,
            limit=25,
        )
        if not rows:
            return await ctx.warn(f"<@{user_id}> has **no punishment history**")
        title = f"History - <@{user_id}>"
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
        target_label = f"`{row['target_id']}`"
        moderator_label = f"`{row['moderator_id']}`"
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
    async def history_remove(self, ctx, target: str, case_id: int):
        """remove punishment"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        user_id = await self._resolve_user_id(ctx, target)
        row = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not row or row["target_id"] != user_id:
            raise CommandError(f"case **#{case_id}** was not found for <@{user_id}>")
        await self.db.execute(
            "DELETE FROM modlog_cases WHERE guild_id = $1 AND case_id = $2",
            ctx.guild.id,
            case_id,
        )
        return await ctx.success(f"Removed case **#{case_id}** for <@{user_id}>")

    @history.command(
        name="removeall",
        description="Remove all punishments from a member",
    )
    @has_permissions(administrator=True)
    async def history_removeall(self, ctx, target: str):
        """remove all punishments"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        user_id = await self._resolve_user_id(ctx, target)
        result = await self.db.execute(
            "DELETE FROM modlog_cases WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id,
            user_id,
        )
        return await ctx.success(f"Cleared punishment history for <@{user_id}> ({result})")
