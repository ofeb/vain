from __future__ import annotations

import asyncio
import contextlib
import io
import json
from collections import defaultdict
from typing import Optional, Union

import discord
from discord import Embed, File, HTTPException, Interaction, Member, Message, Role, TextChannel, User
from discord.ext.commands import Author, BucketType, cooldown, group, command
from discord.ui import Button, View
from asyncpg import UniqueViolationError
from PIL import Image, ImageDraw, ImageFont

from core.discord.package import Package
from core.managers.permissions import has_permissions

FONT_BOLD = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Bold.ttf"
FONT_SEMI = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-SemiBold.ttf"
FONT_MED = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Medium.ttf"
FONT_REG = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Regular.ttf"
FONT_POPPINS_BOLD = "/usr/share/fonts/SlidesCarnival/google/Poppins/Poppins-Bold.ttf"

def _load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def _circular_avatar(avatar: Image.Image, size: int = 140) -> Image.Image:
    avatar = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(avatar, (0, 0), mask)
    return output

async def generate_rank_card(member, level, xp, target_xp, rank, total_members) -> io.BytesIO:
    W, H = 934, 282
    progress = min(xp / target_xp, 1.0) if target_xp > 0 else 0.0
    base = Image.new("RGBA", (W, H), (22, 22, 32, 255))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=24, fill=(22, 22, 32, 255))
    draw.rounded_rectangle([0, 0, 8, H - 1], radius=4, fill=(88, 101, 242, 255))
    try:
        avatar_img = Image.open(io.BytesIO(await member.display_avatar.read())).convert("RGBA")
    except Exception:
        avatar_img = Image.new("RGBA", (180, 180), (60, 60, 80, 255))
    avatar = _circular_avatar(avatar_img, 148)
    base.paste(avatar, (100 - 74, H // 2 - 74), avatar)
    font_name = _load_font(FONT_BOLD, 32)
    font_level = _load_font(FONT_POPPINS_BOLD, 48)
    font_rank = _load_font(FONT_BOLD, 22)
    font_xp = _load_font(FONT_SEMI, 18)
    name = member.display_name[:17] + "\u2026" if len(member.display_name) > 18 else member.display_name
    draw.text((210, 48), name, font=font_name, fill=(245, 245, 250, 255))
    draw.text((210, 92), f"RANK #{rank}", font=font_rank, fill=(160, 160, 180, 255))
    lvl_w = draw.textlength(str(level), font=font_level)
    draw.text((W - 60 - lvl_w, 40), str(level), font=font_level, fill=(255, 255, 255, 255))
    bar_x, bar_y, bar_w, bar_h = 210, 175, 560, 22
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=11, fill=(40, 40, 55, 255))
    fill_w = max(int(bar_w * progress), 8 if progress > 0 else 0)
    if fill_w:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=11, fill=(88, 101, 242, 255))
    draw.text((bar_x, bar_y + 32), f"{xp:,}  /  {target_xp:,} XP", font=font_xp, fill=(180, 180, 200, 255))
    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf

class ConfirmView(View):
    def __init__(self, author_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: Optional[bool] = None
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: Interaction, button: Button):
        self.value = True
        self.stop()
        await interaction.response.defer()
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: Interaction, button: Button):
        self.value = False
        self.stop()
        await interaction.response.defer()

class Leveling(Package):
    """Server leveling, rank cards, multipliers & role rewards."""
    def __init__(self, bot):
        super().__init__(bot)
        self.description = "Leveling system with rank cards, multipliers and rewards"
        self._xp_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
    def _calc_target(self, level: int) -> int:
        return max(int((100 * level + 1) ** 0.9), 50)
    @command(name="rank", aliases=["level", "lvl", "lv"], description="Show your (or someone else's) level card", example=",rank @user", usage="[member]")
    async def rank(self, ctx, *, member: Union[Member, User] = Author):
        if isinstance(member, User) and not isinstance(member, Member):
            member = ctx.guild.get_member(member.id) or member
        rows = await self.db.fetch("SELECT * FROM level_user WHERE guild_id = $1", ctx.guild.id)
        if not rows:
            return await ctx.warn("No one has ranked up in this server yet")
        sorted_rows = sorted(rows, key=lambda r: (r["level"], r["xp"]), reverse=True)
        position = next((i + 1 for i, r in enumerate(sorted_rows) if r["user_id"] == member.id), None)
        if position is None:
            return await ctx.warn(f"{member.mention} has no recorded level data")
        data = next(r for r in sorted_rows if r["user_id"] == member.id)
        card = await generate_rank_card(member if isinstance(member, Member) else ctx.author, data["level"], int(data["xp"]), int(data["target_xp"]), position, len(sorted_rows))
        return await ctx.send(file=File(card, filename=f"rank-{member.id}.png"))
    @group(name="leveling", aliases=["lvlsys", "levels", "levelling"], description="Configure the server leveling system", invoke_without_command=True, example=",leveling")
    @has_permissions(manage_guild=True)
    async def leveling(self, ctx) -> Message:
        return await ctx.send_help()
    @leveling.command(name="enable", description="Turn the leveling system on for this server", example=",leveling enable")
    @has_permissions(manage_guild=True)
    async def leveling_enable(self, ctx):
        exists = await self.db.fetchrow("SELECT 1 FROM leveling WHERE guild_id = $1", ctx.guild.id)
        if exists:
            return await ctx.warn("Leveling is already enabled")
        await self.db.execute(
            "INSERT INTO leveling (guild_id, message, multiplier, booster, stack, command) VALUES ($1, $2, 1.0, 1.0, false, false)",
            ctx.guild.id, "Nice work {user.mention} — you reached **Level {level}**!",
        )
        return await ctx.success("Leveling system is now **enabled**")
    @leveling.command(name="leaderboard", aliases=["lb", "top"], description="Show the highest ranked members", example=",leveling leaderboard")
    async def leveling_leaderboard(self, ctx):
        rows = await self.db.fetch("SELECT * FROM level_user WHERE guild_id = $1", ctx.guild.id)
        member_ids = {m.id for m in ctx.guild.members}
        filtered = [r for r in rows if r["user_id"] in member_ids]
        if not filtered:
            return await ctx.warn("No ranked members yet")
        sorted_rows = sorted(filtered, key=lambda r: (r["level"], r["xp"]), reverse=True)[:15]
        lines = [f"`#{i:02}` **{self.bot.get_user(r['user_id']) or r['user_id']}** — Level **{r['level']}**" for i, r in enumerate(sorted_rows, 1)]
        embed = Embed(title="Level Leaderboard", description="\n".join(lines), color=0x5865F2)
        return await ctx.send(embed=embed)

async def setup(bot) -> None:
    await bot.add_cog(Leveling(bot))
