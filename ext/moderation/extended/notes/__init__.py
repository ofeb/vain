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


_ID_RE = re.compile(r"^\d{15,22}$")
_MENTION_RE = re.compile(r"^<@!?(\d{15,22})>$")


class Notes(Package):
    """Staff notes on members."""

    async def _resolve_user(self, ctx, target: str) -> tuple[int, str]:
        """Resolve target to (user_id, display_label).

        Strict rules:
          1. Mention <@id> / <@!id>  -> force that ID
          2. Pure snowflake (15-22 digits) -> force that ID, never name-match
          3. Exact name / global_name / nick / name#discrim in guild members
          4. Exact name / global_name in bot.users cache
          5. Fail cleanly — never fuzzy, never pick a different user
        Offline users work when given by ID.
        """
        raw = (target or "").strip()
        if not raw:
            raise CommandError("provide a user mention, id, or name")

        uid: int | None = None

        mention_match = _MENTION_RE.match(raw)
        if mention_match:
            uid = int(mention_match.group(1))
        elif _ID_RE.match(raw):
            uid = int(raw)

        if uid is not None:
            if ctx.guild:
                member = ctx.guild.get_member(uid)
                if member is not None:
                    return member.id, str(member)
                try:
                    member = await ctx.guild.fetch_member(uid)
                    return member.id, str(member)
                except (discord.NotFound, discord.HTTPException):
                    pass
            cached = self.bot.get_user(uid)
            if cached is not None:
                return cached.id, f"{cached} (`{cached.id}`")
            try:
                user = await self.bot.fetch_user(uid)
                return user.id, f"{user} (`{user.id}`")
            except (discord.NotFound, discord.HTTPException):
                return uid, f"<@{uid}>"

        lowered = raw.lower()

        if ctx.guild:
            exact: list[discord.Member] = []
            for m in ctx.guild.members:
                candidates = {
                    m.name.lower(),
                    str(m).lower(),
                }
                if m.global_name:
                    candidates.add(m.global_name.lower())
                if m.nick:
                    candidates.add(m.nick.lower())
                if m.discriminator and m.discriminator != "0":
                    candidates.add(f"{m.name.lower()}#{m.discriminator}")
                if lowered in candidates:
                    exact.append(m)
            if len(exact) == 1:
                m = exact[0]
                return m.id, str(m)
            if len(exact) > 1:
                raise CommandError(
                    f"multiple members match `{target}` - use an id or mention instead"
                )

        exact_users: list[discord.User] = []
        for u in self.bot.users:
            candidates = {u.name.lower(), str(u).lower()}
            if u.global_name:
                candidates.add(u.global_name.lower())
            if u.discriminator and u.discriminator != "0":
                candidates.add(f"{u.name.lower()}#{u.discriminator}")
            if lowered in candidates:
                exact_users.append(u)
        if len(exact_users) == 1:
            u = exact_users[0]
            return u.id, f"{u} (`{u.id}`")
        if len(exact_users) > 1:
            raise CommandError(
                f"multiple users match `{target}` - use an id or mention instead"
            )

        raise CommandError(f"could not find a user matching `{target}`")

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
