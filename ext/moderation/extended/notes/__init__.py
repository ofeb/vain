from __future__ import annotations

import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.discord.views.embed import panel_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


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
        rows = await self.db.fetch(
            """SELECT id, moderator_id, content, created_at
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
            lines.append(label_line(f"#{row['id']} · {mod_label}", f"{content} {when}".strip()))

        embed = panel_embed(
            title=f"Notes — {member}",
            color=None,
            lines=lines,
            footer=f"{len(rows)} total" if len(rows) > 25 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @notes.command(
        name="add",
        aliases=["create", "new"],
        description="Add a note for a member",
        example=",notes add @member warned for spam",
    )
    @has_permissions(manage_messages=True)
    async def notes_add(self, ctx, member: discord.Member, *, note: str):
        """Add a note for a member."""
        content = note.strip()
        if not content:
            return await ctx.warn("Provide note content")

        row = await self.db.fetchrow(
            """INSERT INTO notes (guild_id, user_id, moderator_id, content)
               VALUES ($1, $2, $3, $4)
               RETURNING id""",
            ctx.guild.id,
            member.id,
            ctx.author.id,
            content[:2000],
        )
        note_id = row["id"] if row else "?"
        return await ctx.success(f"Added note **#{note_id}** on **{member}**")

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


import contextlib  # noqa: E402  used by notes_clear
