from __future__ import annotations

import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.discord.views.embed import panel_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class Proof(Package):
    """Attach media proof to moderation cases."""

    @group(
        name="proof",
        description="Manage proof attachments for moderation cases",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def proof(self, ctx):
        """proof group help"""
        return await ctx.send_help(ctx.command)

    @proof.command(
        name="add",
        aliases=["attach", "create"],
        description="Add proof media to a case",
        example=",proof add 12 https://example.com/image.png",
    )
    @has_permissions(manage_messages=True)
    async def proof_add(self, ctx, case_id: int, media_url: str):
        """add proof to case"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        case = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not case:
            return await ctx.warn(f"Case **#{case_id}** was not found")

        url = media_url.strip()
        if not url.startswith(("http://", "https://")):
            return await ctx.warn("Provide a valid **http(s)** URL")

        row = await self.db.fetchrow(
            """INSERT INTO proofs (guild_id, user_id, moderator_id, case_id, url)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            ctx.guild.id,
            case.get("target_id") or 0,
            ctx.author.id,
            case_id,
            url[:2000],
        )
        pid = row["id"] if row else "?"
        return await ctx.success(f"Added proof **#{pid}** to case **#{case_id}**")

    @proof.command(
        name="list",
        aliases=["ls", "show"],
        description="List proof for a case",
        example=",proof list 12",
    )
    @has_permissions(manage_messages=True)
    async def proof_list(self, ctx, case_id: int):
        """list proof for case"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        rows = await self.db.fetch(
            """SELECT id, url, moderator_id, created_at
               FROM proofs
               WHERE guild_id = $1 AND case_id = $2
               ORDER BY id ASC""",
            ctx.guild.id,
            case_id,
        )
        if not rows:
            return await ctx.warn(f"No proof attached to case **#{case_id}**")

        lines = []
        for row in rows:
            mod = ctx.guild.get_member(row["moderator_id"])
            mod_label = mod.mention if mod else f"`{row['moderator_id']}`"
            when = discord.utils.format_dt(row["created_at"], style="R") if row.get("created_at") else ""
            lines.append(label_line(f"#{row['id']} · {mod_label}", f"{row['url'][:80]} {when}".strip()))

        embed = panel_embed(
            title=f"Proof — Case #{case_id}",
            color=self.color,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @proof.command(
        name="view",
        aliases=["get"],
        description="View proof for a case (sends URLs)",
        example=",proof view 12",
    )
    @has_permissions(manage_messages=True)
    async def proof_view(self, ctx, case_id: int):
        """view proof for case"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        rows = await self.db.fetch(
            "SELECT id, url FROM proofs WHERE guild_id = $1 AND case_id = $2 ORDER BY id ASC",
            ctx.guild.id,
            case_id,
        )
        if not rows:
            return await ctx.warn(f"No proof attached to case **#{case_id}**")

        urls = "\n".join(f"**#{r['id']}** {r['url']}" for r in rows[:15])
        embed = panel_embed(
            title=f"Proof — Case #{case_id}",
            color=self.color,
            lines=[urls],
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @proof.command(
        name="remove",
        aliases=["delete", "del"],
        description="Remove a proof entry by id",
        example=",proof remove 12 3",
    )
    @has_permissions(manage_messages=True)
    async def proof_remove(self, ctx, case_id: int, index: int):
        """remove proof from case by proof id"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        result = await self.db.execute(
            "DELETE FROM proofs WHERE guild_id = $1 AND case_id = $2 AND id = $3",
            ctx.guild.id,
            case_id,
            index,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"Proof **#{index}** not found for case **#{case_id}**")
        return await ctx.success(f"Removed proof **#{index}** from case **#{case_id}**")

    @proof.command(
        name="set",
        description="Set / replace the primary proof URL for a case",
        example=",proof set 12 https://example.com/evidence.png",
    )
    @has_permissions(manage_messages=True)
    async def proof_set(self, ctx, case_id: int, *, media_url: str):
        """set primary proof for case (clears previous then adds)"""
        if getattr(self.db, "pool", None) is None:
            return await ctx.warn("Database is unavailable")

        case = await self.db.fetch_modlog_case(ctx.guild.id, case_id)
        if not case:
            return await ctx.warn(f"Case **#{case_id}** was not found")

        url = media_url.strip()
        if not url.startswith(("http://", "https://")):
            return await ctx.warn("Provide a valid **http(s)** URL")

        await self.db.execute(
            "DELETE FROM proofs WHERE guild_id = $1 AND case_id = $2",
            ctx.guild.id,
            case_id,
        )
        row = await self.db.fetchrow(
            """INSERT INTO proofs (guild_id, user_id, moderator_id, case_id, url)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            ctx.guild.id,
            case.get("target_id") or 0,
            ctx.author.id,
            case_id,
            url[:2000],
        )
        pid = row["id"] if row else "?"
        return await ctx.success(f"Set proof **#{pid}** for case **#{case_id}**")
