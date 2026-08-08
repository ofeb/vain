from __future__ import annotations

import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.discord.views.embed import panel_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class Restrictcommand(Package):
    """Restrict commands so only specific roles can use them."""

    @group(
        name="restrictcommand",
        aliases=["restrictcmd", "cmdrestrict"],
        description="Only allows people with a certain role to use a command",
        invoke_without_command=True,
        example=",restrictcommand add ban @Staff",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand(self, ctx):
        """restrictcommand group help"""
        return await ctx.send_help(ctx.command)

    @restrictcommand.command(
        name="add",
        aliases=["set", "create"],
        description="Allows the specified role exclusive permission to use a command",
        example=",restrictcommand add ban @Staff",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_add(self, ctx, cmd: str, role: discord.Role):
        """add command restriction"""
        command_name = cmd.lower().strip()
        if not command_name:
            return await ctx.warn("Provide a command name")

        existing = await self.db.fetchval(
            "SELECT 1 FROM command_restrictions WHERE guild_id = $1 AND command = $2 AND role_id = $3",
            ctx.guild.id,
            command_name,
            role.id,
        )
        if existing:
            return await ctx.warn(
                f"{role.mention} already has exclusive access to **{command_name}**"
            )

        await self.db.execute(
            """INSERT INTO command_restrictions (guild_id, command, role_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, command, role_id) DO NOTHING""",
            ctx.guild.id,
            command_name,
            role.id,
        )
        return await ctx.success(
            f"{role.mention} can now exclusively use **{command_name}**"
        )

    @restrictcommand.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="Removes the specified roles exclusive permission to use a command",
        example=",restrictcommand remove ban @Staff",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_remove(self, ctx, cmd: str, role: discord.Role):
        """remove command restriction"""
        command_name = cmd.lower().strip()
        result = await self.db.execute(
            "DELETE FROM command_restrictions WHERE guild_id = $1 AND command = $2 AND role_id = $3",
            ctx.guild.id,
            command_name,
            role.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"{role.mention} does not have a restriction on **{command_name}**"
            )
        return await ctx.success(
            f"Removed exclusive access for {role.mention} on **{command_name}**"
        )

    @restrictcommand.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of every restricted command",
        example=",restrictcommand list",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_list(self, ctx, role_or_command: str | None = None):
        """list restricted commands"""
        if role_or_command:
            
            role = None
            try:
                role = await discord.ext.commands.RoleConverter().convert(ctx, role_or_command)
            except Exception:
                pass

            if role:
                rows = await self.db.fetch(
                    "SELECT command FROM command_restrictions WHERE guild_id = $1 AND role_id = $2 ORDER BY command",
                    ctx.guild.id,
                    role.id,
                )
                if not rows:
                    return await ctx.warn(f"{role.mention} has no restricted commands")
                lines = [f"`{r['command']}`" for r in rows]
                embed = panel_embed(
                    title=f"Restricted Commands - {role.name}",
                    color=None,
                    lines=lines,
                    timestamp=False,
                )
                return await ctx.send(embed=embed)

            
            cmd = role_or_command.lower().strip()
            rows = await self.db.fetch(
                "SELECT role_id FROM command_restrictions WHERE guild_id = $1 AND command = $2",
                ctx.guild.id,
                cmd,
            )
            if not rows:
                return await ctx.warn(f"No restrictions on **{cmd}**")
            lines = []
            for r in rows:
                role_obj = ctx.guild.get_role(r["role_id"])
                lines.append(role_obj.mention if role_obj else f"`{r['role_id']}`")
            embed = panel_embed(
                title=f"Restrictions - {cmd}",
                color=None,
                lines=lines,
                timestamp=False,
            )
            return await ctx.send(embed=embed)

        rows = await self.db.fetch(
            "SELECT command, role_id FROM command_restrictions WHERE guild_id = $1 ORDER BY command",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No command restrictions are set")

        lines = []
        for row in rows[:40]:
            role = ctx.guild.get_role(row["role_id"])
            role_label = role.mention if role else f"`{row['role_id']}`"
            lines.append(label_line(f"`{row['command']}`", role_label))

        embed = panel_embed(
            title=f"Restricted Commands ({len(rows)})",
            color=None,
            lines=lines,
            footer=f"{len(rows)} total" if len(rows) > 40 else None,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @restrictcommand.command(
        name="reset",
        aliases=["clear", "wipe"],
        description="Removes every restricted command. This cannot be undone.",
    )
    @has_permissions(manage_guild=True)
    async def restrictcommand_reset(self, ctx):
        """reset all command restrictions"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** command restrictions for this server? "
            "This action **cannot be undone**."
        )
        if not ok:
            return await ctx.warn("Command restrictions reset **cancelled**")
        result = await self.db.execute(
            "DELETE FROM command_restrictions WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success(
            f"Cleared all command restrictions ({result}). "
            "This action cannot be undone."
        )
