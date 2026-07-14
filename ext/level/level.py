from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import tasks

from core.discord.package import Package

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from core.managers.values import color
from core.tools.aesthetic import aesthetic_embed, panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

XP_PER_MESSAGE = 15
XP_COOLDOWN = 60
LEVEL_BASE = 100
LEVEL_MULTIPLIER = 50


def xp_for_level(level: int) -> int:
    return LEVEL_BASE + (level * LEVEL_MULTIPLIER)


def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level


from .events import LevelEvents


class Level(LevelEvents, Package):
    """XP tracking, level roles, and leaderboards."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._cooldowns: dict[int, float] = {}
    @group(
        name="level",
        description="View your current level and XP",
        invoke_without_command=True,
        aliases=["lvl", "rank", "xp"],
    )
    async def level(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        try:
            row = await self.bot.db.fetchrow(
                "SELECT xp FROM levels WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id, member.id,
            )
            xp = row[0] if row else 0
            lvl = level_from_xp(xp)
            current_level_xp = xp_for_level(lvl)
            xp_in_level = xp - sum(xp_for_level(i) for i in range(lvl))
            xp_needed = current_level_xp

            embed = panel_embed(
                title=f"Level — {member.display_name}",
                color=color.base,
                lines=[],
                thumbnail=member.display_avatar.url,
                timestamp=False,
            )
            embed.add_field(name="Level", value=str(lvl), inline=True)
            embed.add_field(name="XP", value=f"{xp_in_level}/{xp_needed}", inline=True)
            embed.add_field(name="Total XP", value=str(xp), inline=True)

            bar_length = 20
            filled = int((xp_in_level / xp_needed) * bar_length) if xp_needed else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            embed.add_field(name="Progress", value=bar, inline=False)
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Level data unavailable.")

    @level.command(
        name="leaderboard",
        description="View the top ranked members",
        aliases=["lb", "top"],
    )
    async def level_leaderboard(self, ctx: Context) -> None:
        try:
            rows = await self.bot.db.fetch(
                "SELECT user_id, xp FROM levels WHERE guild_id = $1 ORDER BY xp DESC LIMIT 10",
                ctx.guild.id,
            )
            if not rows:
                await ctx.warn("No rankings available yet.")
                return

            entries = []
            for i, row in enumerate(rows, 1):
                user = ctx.guild.get_member(row[0])
                name = user.display_name if user else f"Unknown ({row[0]})"
                lvl = level_from_xp(row[1])
                entries.append(f"`{i}.` **{name}** — Level {lvl} ({row[1]} XP)")

            embed = panel_embed(
                title=f"Leaderboard — {ctx.guild.name}",
                color=color.base,
                lines=entries,
                timestamp=False,
            )
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Leaderboard unavailable.")

    @level.command(
        name="roles",
        description="View level reward roles",
        aliases=["rewards"],
    )
    async def level_roles(self, ctx: Context) -> None:
        try:
            rows = await self.bot.db.fetch(
                "SELECT role_id, level FROM level_roles WHERE guild_id = $1 ORDER BY level",
                ctx.guild.id,
            )
            if not rows:
                await ctx.warn("No reward roles configured.")
                return

            entries = []
            for row in rows:
                role = ctx.guild.get_role(row[0])
                if role:
                    entries.append(f"Level **{row[1]}** — {role.mention}")

            embed = panel_embed(
                title="Level Rewards",
                color=color.base,
                lines=entries,
                timestamp=False,
            )
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Reward roles unavailable.")

    @level.command(
        name="add",
        description="Add a level reward role",
    )
    @describe(level="Level required", role="Role to reward")
    @has_permissions(manage_guild=True)
    async def level_add(self, ctx: Context, level: int, role: discord.Role) -> None:
        if level < 1:
            await ctx.fail("Level must be 1 or higher.")
            return
        try:
            await self.bot.db.execute(
                "INSERT INTO level_roles (guild_id, role_id, level) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                ctx.guild.id, role.id, level,
            )
            await ctx.success(f"{role.mention} will be awarded at level **{level}**.")
        except Exception:
            await ctx.fail("Failed to add reward role.")

    @level.command(
        name="remove",
        description="Remove a level reward role",
        aliases=["delete"],
    )
    @describe(role="Role to remove from rewards")
    @has_permissions(manage_guild=True)
    async def level_remove(self, ctx: Context, role: discord.Role) -> None:
        try:
            await self.bot.db.execute(
                "DELETE FROM level_roles WHERE guild_id = $1 AND role_id = $2",
                ctx.guild.id, role.id,
            )
            await ctx.success(f"Removed {role.mention} from level rewards.")
        except Exception:
            await ctx.fail("Failed to remove reward role.")

    @level.command(
        name="config",
        description="View level system configuration",
        aliases=["settings"],
    )
    async def level_config(self, ctx: Context) -> None:
        try:
            total = await self.bot.db.fetchval(
                "SELECT COUNT(*) FROM levels WHERE guild_id = $1", ctx.guild.id,
            )
            roles = await self.bot.db.fetch(
                "SELECT COUNT(*) FROM level_roles WHERE guild_id = $1", ctx.guild.id,
            )
            embed = panel_embed(
                title="Level Configuration",
                color=color.base,
                lines=[],
                timestamp=False,
            )
            embed.add_field(name="Tracked Members", value=str(total), inline=True)
            embed.add_field(name="Reward Roles", value=str(roles[0][0] if roles else 0), inline=True)
            embed.add_field(name="XP Per Message", value=str(XP_PER_MESSAGE), inline=True)
            embed.add_field(name="Cooldown", value=f"{XP_COOLDOWN}s", inline=True)
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Configuration unavailable.")
async def setup(bot: Vain):
    await bot.add_cog(Level(bot))
