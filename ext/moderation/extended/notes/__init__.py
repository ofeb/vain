from __future__ import annotations

import contextlib

import discord
from discord.ext.commands import group, CommandError

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.discord.views.embed import panel_embed
from core.tools.convert.member import resolve_user


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class Notes(Package):
    """Staff notes on members."""

    async def _noted_users(self, guild_id: int) -> list[discord.User]:
        """Users who already have notes in this guild (for offline name lookup)."""
        try:
            rows = await self.db.fetch(
                "SELECT DISTINCT user_id FROM notes WHERE guild_id = $1",
                guild_id,
            )
        except Exception:
            return []
        users: list[discord.User] = []
        for row in rows:
            uid = int(row["user_id"])
            cached = self.bot.get_user(uid)
            if cached is not None:
                users.append(cached)
                continue
            try:
                user = await self.bot.fetch_user(uid)
                users.append(user)
            except (discord.NotFound, discord.HTTPException):
                continue
        return users

    async def _resolve_user(self, ctx, target: str) -> tuple[int, str]:
        """Resolve target to (user_id, display_label).

        Uses shared resolver: ID/mention, guild regex name match, then
        users who previously had notes in this guild (so left members still
        resolve by username), then bot cache.
        """
        extra: list[discord.User] = []
        if ctx.guild is not None:
            extra = await self._noted_users(ctx.guild.id)
        return await resolve_user(ctx, target, extra_users=extra)

    @group(
        name="notes",
        aliases=["note"],
        description="View and manage staff notes on a member",
        invoke_without_command=True,
        example=",notes @member",
    )
    @has_permissions(manage_messages=True)
    async def notes(self, ctx, target: str):
        """View notes for a user (mention, id, or name — works offline)."""
        with contextlib.suppress(Exception):
            await self.db.execute(
                "ALTER TABLE notes ADD COLUMN IF NOT EXISTS case_id BIGINT"
            )

        try:
            user_id, label = await self._resolve_user(ctx, target)
        except CommandError as e:
            return await ctx.warn(str(e))

        rows = await self.db.fetch(
            """SELECT id, moderator_id, content, created_at, case_id
               FROM notes
               WHERE guild_id = $1 AND user_id = $2
               ORDER BY created_at DESC""",
            ctx.guild.id,
            user_id,
        )
        if not rows:
            return await ctx.warn(f"No notes on **{label}**")

        lines = []
        for row in rows[:25]:
            mod = ctx.guild.get_member(row["moderator_id"]) if ctx.guild else None
            mod_label = mod.mention if mod else f"`{row['moderator_id']}`"
            when = (
                discord.utils.format_dt(row["created_at"], style="R")
                if row["created_at"]
                else ""
            )
            content = (row["content"] or "")[:200]
            case_id = row.get("case_id")
            case_suffix = f" · case #{case_id}" if case_id is not None else ""
            lines.append(
                label_line(
                    f"#{row['id']} · {mod_label}{case_suffix}",
                    f"{content} {when}".strip(),
                )
            )

        embed = panel_embed(
            title=f"Notes - {label}",
            color=None,
            lines=lines,
            footer=f"{len(rows)} total" if len(rows) > 25 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @notes.command(
        name="add",
        aliases=["create", "new"],
        description="Add a note. Pass a user (mention/id/name) or a case id, then the note text.",
        example=",notes add @member warned for spam",
    )
    @has_permissions(manage_messages=True)
    async def notes_add(self, ctx, target: str, *, note: str):
        """Add a note for a member or attach one to a case.

        Syntax:
          ,notes add <user> <note>
          ,notes add <case_id> <note>
        """
        with contextlib.suppress(Exception):
            await self.db.execute(
                "ALTER TABLE notes ADD COLUMN IF NOT EXISTS case_id BIGINT"
            )

        note_body = (note or "").strip()
        if not note_body:
            return await ctx.warn("Provide note content")

        case_id: int | None = None
        user_id: int | None = None
        member_label: str = target

        if target.isdigit() and len(target) < 15:
            cid = int(target)
            case_row = await self.db.fetchrow(
                """SELECT target_id FROM modlog_cases
                   WHERE guild_id = $1 AND case_id = $2""",
                ctx.guild.id,
                cid,
            )
            if case_row and case_row.get("target_id"):
                case_id = cid
                user_id = int(case_row["target_id"])
                member = ctx.guild.get_member(user_id) if ctx.guild else None
                member_label = str(member) if member else f"<@{user_id}>"

        if user_id is None:
            try:
                user_id, member_label = await self._resolve_user(ctx, target)
            except CommandError as e:
                return await ctx.warn(str(e))

        row = await self.db.fetchrow(
            """INSERT INTO notes (guild_id, user_id, moderator_id, content, case_id)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            ctx.guild.id,
            user_id,
            ctx.author.id,
            note_body[:2000],
            case_id,
        )
        note_id = row["id"] if row else "?"
        extra = f" (case **#{case_id}**)" if case_id is not None else ""
        return await ctx.success(f"Added note **#{note_id}** on **{member_label}**{extra}")

    @notes.command(
        name="remove",
        aliases=["delete", "del"],
        description="Remove a note by id",
        example=",notes remove @member 3",
    )
    @has_permissions(manage_messages=True)
    async def notes_remove(self, ctx, target: str, id: int):
        """Remove a note for a user."""
        try:
            user_id, label = await self._resolve_user(ctx, target)
        except CommandError as e:
            return await ctx.warn(str(e))

        result = await self.db.execute(
            "DELETE FROM notes WHERE guild_id = $1 AND user_id = $2 AND id = $3",
            ctx.guild.id,
            user_id,
            id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"Note **#{id}** not found for **{label}**")
        return await ctx.success(f"Removed note **#{id}** from **{label}**")

    @notes.command(
        name="clear",
        description="Clear all notes for a member",
        example=",notes clear @member",
    )
    @has_permissions(manage_messages=True)
    async def notes_clear(self, ctx, target: str):
        """Clear notes for a user."""
        try:
            user_id, label = await self._resolve_user(ctx, target)
        except CommandError as e:
            return await ctx.warn(str(e))

        result = await self.db.execute(
            "DELETE FROM notes WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            user_id,
        )
        count = 0
        if isinstance(result, str) and result.startswith("DELETE "):
            with contextlib.suppress(ValueError):
                count = int(result.split()[-1])
        if count == 0 and result == "DELETE 0":
            return await ctx.warn(f"**{label}** has no notes")
        return await ctx.success(f"Cleared notes for **{label}**")
