from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import tasks

from core.discord.package import Package

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from config import color

from .settings import Settings as LevelSettings

from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.level")

XP_PER_MESSAGE = 15
XP_COOLDOWN = 60
LEVEL_BASE = 100
LEVEL_MULTIPLIER = 50

def xp_for_level(level: int) -> int:
    return LEVEL_BASE + (level * LEVEL_MULTIPLIER)

def level_from_xp(xp: int) -> int:
    level = 0
    remaining = max(0, int(xp or 0))
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    return level

def xp_into_level(xp: int) -> tuple[int, int, int]:
    """Return (level, xp_progress_in_level, xp_needed_for_next)."""
    level = 0
    remaining = max(0, int(xp or 0))
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    needed = xp_for_level(level)
    return level, remaining, needed

from .events import LevelEvents

class Level(LevelEvents, Package):
    """XP tracking, level roles, and leaderboards."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._cooldowns: dict[int, float] = {}

    async def _ensure_tables(self) -> None:
        """Create levels tables if missing (self-heal for older DBs)."""
        try:
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS levels (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    xp BIGINT NOT NULL DEFAULT 0,
                    level INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS level_config (
                    guild_id BIGINT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT TRUE,
                    multiplier INT DEFAULT 1,
                    message TEXT,
                    role_rewards JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS level_roles (
                    guild_id BIGINT,
                    level INT,
                    role_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, level)
                )
                """
            )
        except Exception:
            log.exception("failed ensuring level tables")

    def cog_load(self) -> None:
        self.bot.loop.create_task(self._ensure_tables())

    @group(
        name="level",
        description="View your current level and XP",
        invoke_without_command=True,
        aliases=["lvl", "rank", "xp"],
    )
    async def level(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        try:
            settings = await LevelSettings.fetch(self.bot, ctx.guild)
            row = await self.bot.db.fetchrow(
                "SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                member.id,
            )
            xp = int(row["xp"]) if row else 0
            lvl, xp_in_level, xp_needed = xp_into_level(xp)

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
            if not settings.enabled:
                embed.set_footer(text="Leveling is currently disabled in this server")
            await ctx.send(embed=embed)
        except Exception:
            log.exception("level command failed guild=%s user=%s", ctx.guild.id, member.id)
            await ctx.fail("Level data unavailable.")

    @level.command(
        name="enable",
        description="Enable the leveling system",
        aliases=["on"],
    )
    @has_permissions(manage_guild=True)
    async def level_enable(self, ctx: Context) -> None:
        """Enable XP tracking for this server. Aliases: `on`."""
        try:
            settings = await LevelSettings.fetch(self.bot, ctx.guild)
            await settings.upsert(enabled=True)
            await ctx.success("Leveling is now **enabled**.")
        except Exception:
            log.exception("level enable failed guild=%s", ctx.guild.id)
            await ctx.fail("Couldn't enable leveling.")

    @level.command(
        name="disable",
        description="Disable the leveling system",
        aliases=["off"],
    )
    @has_permissions(manage_guild=True)
    async def level_disable(self, ctx: Context) -> None:
        """Disable XP tracking for this server. Aliases: `off`."""
        try:
            settings = await LevelSettings.fetch(self.bot, ctx.guild)
            await settings.upsert(enabled=False)
            await ctx.success("Leveling is now **disabled**.")
        except Exception:
            log.exception("level disable failed guild=%s", ctx.guild.id)
            await ctx.fail("Couldn't disable leveling.")

    @level.command(
        name="leaderboard",
        description="View the top ranked members",
        aliases=["lb", "top"],
    )
    async def level_leaderboard(self, ctx: Context) -> None:
        try:
            rows = await self.bot.db.fetch(
                "SELECT user_id, xp, level FROM levels WHERE guild_id = $1 ORDER BY xp DESC LIMIT 10",
                ctx.guild.id,
            )
            if not rows:
                await ctx.warn("No rankings available yet.")
                return

            entries = []
            for i, row in enumerate(rows, 1):
                user = ctx.guild.get_member(int(row["user_id"]))
                name = user.display_name if user else f"Unknown ({row['user_id']})"
                xp = int(row["xp"] or 0)
                lvl = int(row["level"] or 0) or level_from_xp(xp)
                entries.append(f"`{i}.` **{name}** — Level {lvl} ({xp} XP)")

            embed = panel_embed(
                title=f"Leaderboard — {ctx.guild.name}",
                color=color.base,
                lines=entries,
                timestamp=False,
            )
            await ctx.send(embed=embed)
        except Exception:
            log.exception("level leaderboard failed guild=%s", ctx.guild.id)
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
                role = ctx.guild.get_role(int(row["role_id"]))
                if role:
                    entries.append(f"Level **{row['level']}** — {role.mention}")

            if not entries:
                await ctx.warn("No reward roles configured.")
                return

            embed = panel_embed(
                title="Level Rewards",
                color=color.base,
                lines=entries,
                timestamp=False,
            )
            await ctx.send(embed=embed)
        except Exception:
            log.exception("level roles failed guild=%s", ctx.guild.id)
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
                """
                INSERT INTO level_roles (guild_id, role_id, level)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, level) DO UPDATE SET role_id = EXCLUDED.role_id
                """,
                ctx.guild.id,
                role.id,
                level,
            )
            await ctx.success(f"{role.mention} will be awarded at level **{level}**.")
        except Exception:
            log.exception("level add failed guild=%s", ctx.guild.id)
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
                ctx.guild.id,
                role.id,
            )
            await ctx.success(f"Removed {role.mention} from level rewards.")
        except Exception:
            log.exception("level remove failed guild=%s", ctx.guild.id)
            await ctx.fail("Failed to remove reward role.")

    @level.command(
        name="config",
        description="View level system configuration",
        aliases=["settings"],
    )
    async def level_config(self, ctx: Context) -> None:
        try:
            settings = await LevelSettings.fetch(self.bot, ctx.guild)
            total = await self.bot.db.fetchval(
                "SELECT COUNT(*) FROM levels WHERE guild_id = $1",
                ctx.guild.id,
            )
            role_count = await self.bot.db.fetchval(
                "SELECT COUNT(*) FROM level_roles WHERE guild_id = $1",
                ctx.guild.id,
            )
            embed = panel_embed(
                title="Level Configuration",
                color=color.base,
                lines=[],
                timestamp=False,
            )
            embed.add_field(
                name="Enabled",
                value="yes" if settings.enabled else "no",
                inline=True,
            )
            embed.add_field(
                name="Multiplier",
                value=str(settings.multiplier or 1),
                inline=True,
            )
            embed.add_field(
                name="Tracked Members",
                value=str(int(total or 0)),
                inline=True,
            )
            embed.add_field(
                name="Reward Roles",
                value=str(int(role_count or 0)),
                inline=True,
            )
            embed.add_field(name="XP Per Message", value=str(XP_PER_MESSAGE), inline=True)
            embed.add_field(name="Cooldown", value=f"{XP_COOLDOWN}s", inline=True)
            await ctx.send(embed=embed)
        except Exception:
            log.exception("level config failed guild=%s", ctx.guild.id)
            await ctx.fail("Configuration unavailable.")

async def setup(bot: Vain):
    await bot.add_cog(Level(bot))
