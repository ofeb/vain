from __future__ import annotations

import contextlib
import re

import discord
from discord.ext import commands
from discord.ext.commands import group, CommandError

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.discord.views.embed import panel_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


_ID_RE = re.compile(r"^\d{15,20}$")


class Notes(Package):
    """Staff notes on members."""

    @group(
        name="notes",
        aliases=["note"],
        description="View and manage staff notes on a member",
        invoke_without_command=True,
        example=",notes @member",
    )
    @has_permissions(manage_messages=True)
    async def notes(self, ctx, member: discord.Member):
        """View notes for a member."""
        with contextlib.suppress(Exception):
            await self.db.execute(
                "ALTER TABLE notes ADD COLUMN IF NOT EXISTS case_id BIGINT"
            )

        rows = await self.db.fetch(
            """SELECT id, moderator_id, content, created_at, case_id
               FROM notes
               WHERE guild_id = $1 AND user_id = $2
               ORDER BY created_at DESC""",
            ctx.guild.id,
            member.id,
        )
        if not rows:
            return await ctx.warn(f"No notes on **{member}**")

        lines = []
        for row in rows[:25]:
            mod = ctx.guild.get_member(row["moderator_id"])
            mod_label = mod.mention if mod else f"`{row['moderator_id']}`"
            when = discord.utils.format_dt(row["created_at"], style="R") if row["created_at"] else ""
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
            title=f"Notes - {member}",
            color=None,
            lines=lines,
            footer=f"{len(rows)} total" if len(rows) > 25 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    async def _resolve_user_id(self, ctx, target: str) -> int:
        raw = target.strip()
        mention_match = re.match(r"<@!?(\d+)>", raw)
        if mention_match:
            return int(mention_match.group(1))
        if _ID_RE.match(raw):
            return int(raw)
        try:
            member = await commands.MemberConverter().convert(ctx, raw)
            return member.id
        except CommandError:
            pass
        try:
            user = await commands.UserConverter().convert(ctx, raw)
            return user.id
        except CommandError:
            raise CommandError(f"could not find a user matching `{target}`")

    @notes.command(
        name="add",
        aliases=["create", "new"],
        description="Add a note. Pass a user (mention/id/name) or a case id, then the note text.",
        example=",notes add @member warned for spam\n,notes add 14 he was being rude",
    )
    @has_permissions(manage_messages=True)
    async def notes_add(self, ctx, target: str, *, note: str):
        """Add a note for a member or attach one to a case.

        Syntax:
          ,notes add <user> <note>          — plain note on the user
          ,notes add <case.id> <note>        — note linked to that case (and its target)
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

        # Short numeric token → try as case id first (snowflakes are 15+ digits)
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
                member = ctx.guild.get_member(user_id)
                member_label = member.mention if member else f"<@{user_id}>"

        if user_id is None:
            try:
                user_id = await self._resolve_user_id(ctx, target)
            except CommandError as e:
                return await ctx.warn(str(e))
            member = ctx.guild.get_member(user_id)
            member_label = member.mention if member else f"<@{user_id}>"

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
    async def notes_remove(self, ctx, member: discord.Member, id: int):
        """Remove a note for a member."""
        result = await self.db.execute(
            "DELETE FROM notes WHERE guild_id = $1 AND user_id = $2 AND id = $3",
            ctx.guild.id,
            member.id,
            id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"Note **#{id}** not found for **{member}**")
        return await ctx.success(f"Removed note **#{id}** from **{member}**")

    @notes.command(
        name="clear",
        description="Clear all notes for a member",
        example=",notes clear @member",
    )
    @has_permissions(manage_messages=True)
    async def notes_clear(self, ctx, member: discord.Member):
        """Clear notes for a member."""
        result = await self.db.execute(
            "DELETE FROM notes WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            member.id,
        )
        count = 0
        if isinstance(result, str) and result.startswith("DELETE "):
            with contextlib.suppress(ValueError):
                count = int(result.split()[-1])
        if count == 0 and result == "DELETE 0":
            return await ctx.warn(f"**{member}** has no notes")
        return await ctx.success(f"Cleared notes for **{member}**")
