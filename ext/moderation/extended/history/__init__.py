from __future__ import annotations

import discord
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.discord.hybrid import hybrid, describe
from core.managers.permissions import has_permissions

from core.discord.views.embed import panel_embed
from core.discord.views.paginate import send_pages
from core.tools.human.time import human_date
from core.tools.convert.member import resolve_user

_CASES_PER_PAGE = 3


class History(Package):
    """history management"""

    def _format_history_case_line(
        self,
        row,
        user_cache: dict[int, str] | None = None,
        note: str | None = None,
    ) -> str:
        cache = user_cache or {}
        moderator_id = row.get("moderator_id")

        if moderator_id and moderator_id in cache:
            moderator = cache[moderator_id]
        elif moderator_id:
            moderator = f"`{moderator_id}`"
        else:
            moderator = "unknown"

        when = human_date(row.get("created_at"), fallback="unknown")
        reason = row.get("reason") or "no reason provided"
        edited_at = row.get("edited_at")
        edited_by = row.get("edited_by")
        case_id = row.get("case_id")

        lines = [
            f"**Case #{case_id}** - `{row['action']}`",
            f"-# **moderator**: {moderator}",
            f"-# **when**: {when}",
            f"-# **reason**: {reason}",
        ]

        if note:
            lines.append(f"-# **note**: {note}")
        else:
            lines.append(
                f"-# **note**: unavailable *(add note using note add {case_id} <reason here>.)*"
            )

        if edited_at:
            edited_when = human_date(edited_at, fallback="unknown")
            if edited_by and edited_by in cache:
                editor = cache[edited_by]
            elif edited_by:
                editor = f"`{edited_by}`"
            else:
                editor = "unknown"
            lines.append(f"-# **edited**: {edited_when} by {editor}")

        return "\n".join(lines)

    def _build_case_pages(
        self,
        rows: list,
        user_cache: dict[int, str],
        title: str,
        notes_by_case: dict[int, str] | None = None,
    ) -> list[discord.Embed]:
        """Build paginated embeds with 3 cases per page."""
        notes_by_case = notes_by_case or {}
        pages = []
        for i in range(0, len(rows), _CASES_PER_PAGE):
            chunk = rows[i : i + _CASES_PER_PAGE]
            lines: list[str] = []
            for idx, row in enumerate(chunk):
                lines.append(
                    self._format_history_case_line(
                        row,
                        user_cache,
                        note=notes_by_case.get(row["case_id"]),
                    )
                )
                # blank spacer between cases so the note line is not jammed
                # against the next Case header
                if idx < len(chunk) - 1:
                    lines.append("\u200b")
            page_num = (i // _CASES_PER_PAGE) + 1
            total_pages = -(-len(rows) // _CASES_PER_PAGE)
            embed = panel_embed(
                title=title,
                color=None,
                lines=lines,
                footer=f"page {page_num}/{total_pages}",
                timestamp=False,
            )
            pages.append(embed)
        return pages

    async def _resolve_user_id(self, ctx, target: str) -> int:
        """Resolve a user ID from mention, id, username, or display name."""
        uid, _label = await resolve_user(ctx, target)
        return uid

    async def _build_user_cache(self, ctx, rows) -> dict[int, str]:
        """Fetch usernames for all IDs in the case rows."""
        ids = set()
        for row in rows:
            if row.get("target_id"):
                ids.add(row["target_id"])
            if row.get("moderator_id"):
                ids.add(row["moderator_id"])
            if row.get("edited_by"):
                ids.add(row["edited_by"])

        cache: dict[int, str] = {}
        for uid in ids:
            if ctx.guild:
                member = ctx.guild.get_member(uid)
                if member:
                    cache[uid] = member.mention
                    continue

            try:
                user = await self.bot.fetch_user(uid)
                cache[uid] = f"{user.name} (`{uid}`)"
            except (discord.NotFound, discord.HTTPException):
                cache[uid] = f"`{uid}`"
        return cache

    async def _fetch_notes_for_cases(
        self, guild_id: int, user_id: int, case_ids: list[int]
    ) -> dict[int, str]:
        """Return mapping case_id -> note content for the given cases."""
        if not case_ids:
            return {}
        try:
            rows = await self.db.fetch(
                """SELECT case_id, content
                   FROM notes
                   WHERE guild_id = $1 AND user_id = $2 AND case_id = ANY($3::BIGINT[])
                   ORDER BY created_at DESC""",
                guild_id,
                user_id,
                case_ids,
            )
        except Exception:
            return {}
        out: dict[int, str] = {}
        for row in rows:
            cid = row["case_id"]
            if cid is not None and cid not in out:
                out[cid] = (row["content"] or "")[:500]
        return out

    @hybrid(
        name="history",
        description="View moderation history for a user",
        group=True,
    )
    @has_permissions(manage_messages=True)
    @describe(target="User ID, mention, or username to check", command="Filter by action type")
    async def history(self, ctx, target: str, command: str | None = None):
        """view history"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        try:
            user_id = await self._resolve_user_id(ctx, target)
        except CommandError as e:
            return await ctx.warn(str(e))
        rows = await self.db.fetch_modlog_cases_for_user(
            ctx.guild.id,
            user_id,
            action=command.lower() if command else None,
            limit=75,
        )
        if not rows:
            return await ctx.warn(f"<@{user_id}> has **no punishment history**")

        user_cache = await self._build_user_cache(ctx, rows)
        case_ids = [r["case_id"] for r in rows if r.get("case_id") is not None]
        notes_by_case = await self._fetch_notes_for_cases(ctx.guild.id, user_id, case_ids)

        target_label = user_cache.get(user_id, f"<@{user_id}>")
        title = f"History - {target_label}"
        if command:
            title += f" ({command})"

        pages = self._build_case_pages(rows, user_cache, title, notes_by_case=notes_by_case)
        await send_pages(ctx, pages)

    @history.command(
        name="view",
        description="View a case log",
    )
    @has_permissions(manage_messages=True)
    async def history_view(self, ctx, case_id: int):
        """view case log"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        row = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not row:
            return await ctx.warn(f"Case **#{case_id}** was not found")

        user_cache = await self._build_user_cache(ctx, [row])

        target_id = row.get("target_id")
        moderator_id = row.get("moderator_id")
        target_label = user_cache.get(target_id, f"`{target_id}`") if target_id else "unknown"
        moderator_label = user_cache.get(moderator_id, f"`{moderator_id}`") if moderator_id else "unknown"

        when = human_date(row.get("created_at"), fallback="unknown")
        reason = row.get("reason") or "no reason provided"

        lines = [
            f"**Action**: `{row['action']}`",
            f"**Target**: {target_label}",
            f"**Moderator**: {moderator_label}",
            f"**Reason**: {reason}",
            f"-# **when**: {when}",
        ]

        note_text = None
        if target_id:
            notes = await self._fetch_notes_for_cases(ctx.guild.id, target_id, [case_id])
            note_text = notes.get(case_id)

        if note_text:
            lines.append(f"-# **note**: {note_text}")
        else:
            lines.append(
                f"-# **note**: unavailable *(add notes using notes add {case_id} he was being rude.)*"
            )

        edited_at = row.get("edited_at")
        edited_by = row.get("edited_by")
        if edited_at:
            edited_when = human_date(edited_at, fallback="unknown")
            editor = user_cache.get(edited_by, f"`{edited_by}`") if edited_by else "unknown"
            lines.append(f"-# **edited**: {edited_when} by {editor}")

        embed = panel_embed(
            color=None,
            title=f"Case #{case_id}",
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @history.command(
        name="edit",
        description="Edit a case's reason",
    )
    @has_permissions(manage_messages=True)
    @describe(case_id="Case number to edit", reason="New reason for the case")
    async def history_edit(self, ctx, case_id: int, *, reason: str):
        """edit case reason"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        row = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not row:
            return await ctx.warn(f"Case **#{case_id}** was not found")

        updated = await self.db.update_case_reason(
            ctx.guild.id,
            case_id,
            reason.strip(),
            ctx.author.id,
        )
        if not updated:
            return await ctx.warn(f"Failed to update case **#{case_id}**")
        return await ctx.success(f"Updated case **#{case_id}** reason")

    @history.command(
        name="remove",
        description="Remove a punishment from a member",
    )
    @has_permissions(manage_messages=True)
    async def history_remove(self, ctx, target: str, case_id: int):
        """remove punishment"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")
        try:
            user_id = await self._resolve_user_id(ctx, target)
        except CommandError as e:
            return await ctx.warn(str(e))
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
        try:
            user_id = await self._resolve_user_id(ctx, target)
        except CommandError as e:
            return await ctx.warn(str(e))
        result = await self.db.execute(
            "DELETE FROM modlog_cases WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id,
            user_id,
        )
        return await ctx.success(f"Cleared punishment history for <@{user_id}> ({result})")
