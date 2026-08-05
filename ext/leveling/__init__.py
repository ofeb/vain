"""Server leveling — Pillow rank cards, multipliers, rewards, ignore lists.

Inspired by classic multipurpose bots; rewritten for Vain's Package layout.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
from collections import defaultdict
from typing import Optional, Union

import discord
from discord import Embed, File, HTTPException, Interaction, Member, Message, Role, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Author, BucketType, cooldown, group, command
from discord.ui import Button, View
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.discord.package import Package
from core.managers.permissions import has_permissions

# Prefer Windows / common Linux font paths
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Bold.ttf",
    "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-SemiBold.ttf",
    "/usr/share/fonts/SlidesCarnival/google/Poppins/Poppins-Bold.ttf",
]

_VALID_MULTIS = (
    0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0,
)


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _circular_avatar(avatar: Image.Image, size: int = 148) -> Image.Image:
    avatar = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(avatar, (0, 0), mask)
    return out


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


async def generate_rank_card(
    member,
    level: int,
    xp: float,
    target_xp: int,
    rank: int,
    total_members: int,
    *,
    accent: int = 0x5865F2,
) -> io.BytesIO:
    """Render a polished rank/level card (Pillow)."""
    W, H = 934, 282
    progress = min(float(xp) / float(target_xp), 1.0) if target_xp > 0 else 0.0
    ar = (accent >> 16) & 0xFF
    ag = (accent >> 8) & 0xFF
    ab = accent & 0xFF

    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)

    # soft shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([10, 14, W - 6, H - 4], radius=28, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    base.alpha_composite(shadow)

    # card body
    _rounded_rect(draw, [0, 0, W - 12, H - 16], 26, (24, 25, 38, 255))
    # left accent bar
    _rounded_rect(draw, [0, 0, 10, H - 16], 6, (ar, ag, ab, 255))
    # subtle top highlight
    _rounded_rect(draw, [14, 10, W - 26, 12], 2, (ar, ag, ab, 40))

    # avatar
    try:
        avatar_bytes = await member.display_avatar.read()
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    except Exception:
        avatar_img = Image.new("RGBA", (180, 180), (60, 62, 80, 255))
    avatar = _circular_avatar(avatar_img, 148)
    # ring
    ring = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, 159, 159), outline=(ar, ag, ab, 255), width=4)
    base.paste(ring, (42, (H - 16) // 2 - 80), ring)
    base.paste(avatar, (48, (H - 16) // 2 - 74), avatar)

    font_name = _load_font(34, bold=True)
    font_rank = _load_font(20, bold=True)
    font_level = _load_font(52, bold=True)
    font_xp = _load_font(18)
    font_small = _load_font(16)

    name = member.display_name
    if len(name) > 18:
        name = name[:17] + "…"
    draw.text((220, 48), name, font=font_name, fill=(245, 246, 252, 255))
    draw.text(
        (220, 96),
        f"RANK  #{rank}  ·  {total_members} members",
        font=font_rank,
        fill=(150, 154, 175, 255),
    )

    lvl_label = "LEVEL"
    draw.text((W - 200, 40), lvl_label, font=font_small, fill=(150, 154, 175, 255))
    lvl_text = str(level)
    try:
        lvl_w = draw.textlength(lvl_text, font=font_level)
    except Exception:
        lvl_w = 40
    draw.text((W - 60 - lvl_w - 12, 52), lvl_text, font=font_level, fill=(255, 255, 255, 255))

    # progress bar
    bar_x, bar_y, bar_w, bar_h = 220, 168, 580, 24
    _rounded_rect(draw, [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], 12, (40, 42, 58, 255))
    fill_w = max(int(bar_w * progress), 10 if progress > 0 else 0)
    if fill_w:
        # gradient-ish by drawing two layers
        _rounded_rect(
            draw,
            [bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
            12,
            (ar, ag, ab, 255),
        )
        _rounded_rect(
            draw,
            [bar_x, bar_y, bar_x + fill_w, bar_y + bar_h // 2],
            12,
            (min(ar + 30, 255), min(ag + 30, 255), min(ab + 30, 255), 90),
        )

    pct = progress * 100
    draw.text(
        (bar_x, bar_y + 32),
        f"{int(xp):,}  /  {int(target_xp):,} XP   ·   {pct:.1f}%",
        font=font_xp,
        fill=(180, 184, 205, 255),
    )

    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


class ConfirmView(View):
    def __init__(self, author_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: Optional[bool] = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This confirmation is not for you.", ephemeral=True
            )
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
    """Server leveling with rank cards, multipliers, and role rewards."""

    def __init__(self, bot):
        super().__init__(bot)
        self.description = "Leveling system with rank cards, multipliers and rewards"
        self._xp_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._cooldowns: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        # Apply schema if present
        from pathlib import Path

        schema = Path(__file__).with_name("schema.sql")
        if schema.exists() and getattr(self.db, "pool", None) is not None:
            try:
                sql = schema.read_text(encoding="utf-8")
                for stmt in sql.split(";"):
                    s = stmt.strip()
                    if s:
                        with contextlib.suppress(Exception):
                            await self.db.execute(s)
            except Exception:
                pass

    def _calc_target(self, level: int) -> int:
        return max(int((100 * level + 1) ** 0.9), 50)

    def _calc_total_xp(self, level: int, xp: float) -> int:
        total = 0
        for lv in range(max(int(level), 0)):
            total += self._calc_target(lv)
        return total + int(xp)

    async def _get_cfg(self, guild_id: int) -> dict | None:
        row = await self.db.fetchrow(
            "SELECT * FROM leveling WHERE guild_id = $1", guild_id
        )
        return dict(row) if row else None

    async def _require_enabled(self, ctx) -> dict | None:
        cfg = await self._get_cfg(ctx.guild.id)
        if not cfg:
            await ctx.warn(
                f"Leveling is not enabled — use `{ctx.clean_prefix}leveling enable`"
            )
            return None
        return cfg

    def _parse_json_list(self, raw) -> list[int]:
        if not raw:
            return []
        if isinstance(raw, list):
            return [int(x) for x in raw]
        try:
            data = json.loads(raw)
            return [int(x) for x in data] if isinstance(data, list) else []
        except Exception:
            return []

    async def _level_replace(self, member: Member, params: str) -> str:
        row = await self.db.fetchrow(
            "SELECT * FROM level_user WHERE guild_id = $1 AND user_id = $2",
            member.guild.id,
            member.id,
        )
        level = str(row["level"]) if row else "1"
        target = str(row["target_xp"]) if row else "100"
        return (
            params.replace("{level}", level)
            .replace("{target_xp}", target)
            .replace("{xp}", str(int(row["xp"])) if row else "0")
        )

    # ------------------------------------------------------------------
    # user-facing rank card
    # ------------------------------------------------------------------

    @command(
        name="rank",
        aliases=["level", "lvl", "lv"],
        description="Show your (or someone else's) level card",
        example=",rank @user",
        usage="[member]",
    )
    async def rank(self, ctx, *, member: Union[Member, User] = Author):
        if isinstance(member, User) and not isinstance(member, Member):
            member = ctx.guild.get_member(member.id) or member
        rows = await self.db.fetch(
            "SELECT * FROM level_user WHERE guild_id = $1", ctx.guild.id
        )
        if not rows:
            return await ctx.warn("No one has ranked up in this server yet")
        sorted_rows = sorted(
            rows, key=lambda r: (r["level"], r["xp"]), reverse=True
        )
        position = next(
            (i + 1 for i, r in enumerate(sorted_rows) if r["user_id"] == member.id),
            None,
        )
        if position is None:
            return await ctx.warn(f"{member.mention} has no recorded level data")
        data = next(r for r in sorted_rows if r["user_id"] == member.id)
        accent = getattr(self.bot, "color", None) or 0x5865F2
        card = await generate_rank_card(
            member if isinstance(member, Member) else ctx.author,
            int(data["level"]),
            float(data["xp"]),
            int(data["target_xp"]),
            position,
            len(sorted_rows),
            accent=int(accent),
        )
        return await ctx.send(file=File(card, filename=f"rank-{member.id}.png"))

    # ------------------------------------------------------------------
    # admin group
    # ------------------------------------------------------------------

    @group(
        name="leveling",
        aliases=["lvlsys", "levels", "levelling"],
        description="Configure the server leveling system",
        invoke_without_command=True,
        example=",leveling",
    )
    @has_permissions(manage_guild=True)
    async def leveling(self, ctx) -> Message:
        return await ctx.send_help()

    @leveling.command(
        name="enable",
        description="Turn the leveling system on for this server",
        example=",leveling enable",
    )
    @has_permissions(manage_guild=True)
    async def leveling_enable(self, ctx):
        if await self.db.fetchrow(
            "SELECT 1 FROM leveling WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.warn("Leveling is already **enabled**")
        await self.db.execute(
            """INSERT INTO leveling
               (guild_id, message, multiplier, booster, stack, command)
               VALUES ($1, $2, 1.0, 1.0, false, false)""",
            ctx.guild.id,
            "Nice work {user.mention} — you reached **Level {level}**!",
        )
        return await ctx.success("Leveling system is now **enabled**")

    @leveling.command(
        name="disable",
        description="Disable leveling and wipe all XP (confirmation required)",
        example=",leveling disable",
    )
    @has_permissions(manage_guild=True)
    async def leveling_disable(self, ctx):
        if not await self._require_enabled(ctx):
            return
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send(
            embed=Embed(
                color=0xED4245,
                description=(
                    f"{ctx.author.mention}: Disable leveling and **wipe all XP**?"
                ),
            ),
            view=view,
        )
        await view.wait()
        with contextlib.suppress(Exception):
            await msg.edit(view=None)
        if not view.value:
            return await ctx.warn("Leveling disable **cancelled**")
        await self.db.execute(
            "DELETE FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        await self.db.execute(
            "DELETE FROM level_user WHERE guild_id = $1", ctx.guild.id
        )
        return await ctx.success("Leveling disabled and statistics wiped")

    @leveling.command(
        name="channel",
        description="Set where level-up messages go (`any`, `dm`, or a channel)",
        example=",leveling channel #levels",
        usage="<channel|any|dm>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_channel(self, ctx, *, channel: str):
        if not await self._require_enabled(ctx):
            return
        raw = channel.strip().lower()
        if raw == "any":
            await self.db.execute(
                "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
                None,
                ctx.guild.id,
            )
            return await ctx.success("Level-ups will post in **any** channel")
        if raw == "dm":
            await self.db.execute(
                "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
                0,
                ctx.guild.id,
            )
            return await ctx.success("Level-ups will be sent in **DMs**")
        try:
            ch = await commands.TextChannelConverter().convert(ctx, channel)
        except Exception:
            return await ctx.warn("Use a channel mention, `any`, or `dm`")
        await self.db.execute(
            "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
            ch.id,
            ctx.guild.id,
        )
        return await ctx.success(f"Level-ups will post in {ch.mention}")

    @leveling.command(
        name="message",
        description="Set the level-up message script (embed/container/plain)",
        example=",leveling message Nice {user.mention} — Level {level}!",
        usage="<script|none>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_message(self, ctx, *, message: str = None):
        if not await self._require_enabled(ctx):
            return
        if message is None:
            return await ctx.send_help(ctx.command)
        if message.strip().lower() == "none":
            await self.db.execute(
                "UPDATE leveling SET message = $1 WHERE guild_id = $2",
                "none",
                ctx.guild.id,
            )
            return await ctx.success("Removed the level-up message")
        await self.db.execute(
            "UPDATE leveling SET message = $1 WHERE guild_id = $2",
            message,
            ctx.guild.id,
        )
        return await ctx.success(f"Level-up message set to:\n```\n{message[:500]}\n```")

    @leveling.command(
        name="test",
        description="Preview the level-up message",
        example=",leveling test",
    )
    @has_permissions(manage_guild=True)
    async def leveling_test(self, ctx):
        cfg = await self._require_enabled(ctx)
        if not cfg:
            return
        script = cfg.get("message") or "none"
        if script == "none":
            return await ctx.warn("No level-up message configured")
        rendered = await self._level_replace(ctx.author, script)
        ch_id = cfg.get("channel_id")
        channel = (
            ctx.guild.get_channel(ch_id)
            if ch_id not in (None, 0)
            else ctx.channel
        )
        try:
            msg = await self.bot.send_embed(
                channel or ctx.channel, rendered, member=ctx.author, user=ctx.author
            )
            return await ctx.success(f"Sent preview → {msg.jump_url}")
        except Exception as e:
            return await ctx.warn(f"Failed to send preview:\n```{e}```")

    def _check_multi(self, value: float) -> bool:
        return float(value) in _VALID_MULTIS

    @leveling.command(
        name="multiplier",
        aliases=["multi"],
        description="Set the global XP multiplier",
        example=",leveling multiplier 1.5",
        usage="<0.25–3.00>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_multiplier(self, ctx, multiplier: float):
        if not await self._require_enabled(ctx):
            return
        if not self._check_multi(multiplier):
            return await ctx.warn(
                "Multiplier must be one of: "
                + ", ".join(f"`{m:.2f}`" for m in _VALID_MULTIS)
            )
        await self.db.execute(
            "UPDATE leveling SET multiplier = $1 WHERE guild_id = $2",
            float(multiplier),
            ctx.guild.id,
        )
        return await ctx.success(f"Global multiplier set to **{multiplier:.2f}**")

    @leveling.command(
        name="booster",
        description="Set the XP multiplier for server boosters",
        example=",leveling booster 2",
        usage="<0.25–3.00>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_booster(self, ctx, multiplier: float):
        if not await self._require_enabled(ctx):
            return
        if not self._check_multi(multiplier):
            return await ctx.warn(
                "Multiplier must be one of: "
                + ", ".join(f"`{m:.2f}`" for m in _VALID_MULTIS)
            )
        await self.db.execute(
            "UPDATE leveling SET booster = $1 WHERE guild_id = $2",
            float(multiplier),
            ctx.guild.id,
        )
        return await ctx.success(f"Booster multiplier set to **{multiplier:.2f}**")

    @leveling.command(
        name="set",
        description="Set a member's level",
        example=",leveling set @user 15",
        usage="<member> <level>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_set(self, ctx, member: Member, level: int):
        if not await self._require_enabled(ctx):
            return
        if level < 1 or level > 1000:
            return await ctx.warn("Level must be between **1** and **1000**")
        target = self._calc_target(level)
        await self.db.execute(
            """INSERT INTO level_user (guild_id, user_id, xp, level, target_xp)
               VALUES ($1, $2, 0, $3, $4)
               ON CONFLICT (guild_id, user_id)
               DO UPDATE SET xp = 0, level = $3, target_xp = $4""",
            ctx.guild.id,
            member.id,
            level,
            target,
        )
        await self._sync_user_roles(ctx.guild, member, level)
        return await ctx.success(
            f"Set {member.mention} to **Level {level}**"
        )

    @leveling.command(
        name="reset",
        description="Reset a member's XP (or everyone with no member)",
        example=",leveling reset @user",
        usage="[member]",
    )
    @has_permissions(manage_guild=True)
    async def leveling_reset(self, ctx, member: Member = None):
        if not await self._require_enabled(ctx):
            return
        view = ConfirmView(ctx.author.id)
        target = member.mention if member else "**everyone**"
        msg = await ctx.send(
            embed=Embed(
                color=0xED4245,
                description=f"{ctx.author.mention}: Reset level stats for {target}?",
            ),
            view=view,
        )
        await view.wait()
        with contextlib.suppress(Exception):
            await msg.edit(view=None)
        if not view.value:
            return await ctx.warn("Reset **cancelled**")
        if member is None:
            await self.db.execute(
                "DELETE FROM level_user WHERE guild_id = $1", ctx.guild.id
            )
            return await ctx.success("Reset level stats for **all** members")
        await self.db.execute(
            "DELETE FROM level_user WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            member.id,
        )
        return await ctx.success(f"Reset level stats for {member.mention}")

    @leveling.command(
        name="leaderboard",
        aliases=["lb", "top"],
        description="Show the highest ranked members",
        example=",leveling leaderboard",
    )
    async def leveling_leaderboard(self, ctx):
        rows = await self.db.fetch(
            "SELECT * FROM level_user WHERE guild_id = $1", ctx.guild.id
        )
        member_ids = {m.id for m in ctx.guild.members}
        filtered = [r for r in rows if r["user_id"] in member_ids]
        if not filtered:
            return await ctx.warn("No ranked members yet")
        sorted_rows = sorted(
            filtered, key=lambda r: (r["level"], r["xp"]), reverse=True
        )[:25]
        lines = []
        for i, r in enumerate(sorted_rows, 1):
            user = self.bot.get_user(r["user_id"]) or r["user_id"]
            lines.append(
                f"`#{i:02}` **{user}** — Level **{r['level']}** "
                f"(`{int(r['xp']):,}`/`{int(r['target_xp']):,}` XP)"
            )
        embed = Embed(
            title="Level Leaderboard",
            description="\n".join(lines),
            color=getattr(self.bot, "color", 0x5865F2) or 0x5865F2,
        )
        if ctx.guild.icon:
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url)
        return await ctx.send(embed=embed)

    @leveling.command(
        name="config",
        aliases=["settings", "status"],
        description="View leveling configuration",
        example=",leveling config",
    )
    @has_permissions(manage_guild=True)
    async def leveling_config(self, ctx):
        cfg = await self._require_enabled(ctx)
        if not cfg:
            return
        ch_id = cfg.get("channel_id")
        if ch_id == 0:
            ch_label = "DMs"
        elif ch_id:
            ch = ctx.guild.get_channel(ch_id)
            ch_label = ch.mention if ch else f"`{ch_id}`"
        else:
            ch_label = "any"
        embed = Embed(title="Leveling Config", color=0x5865F2)
        embed.add_field(name="Channel", value=ch_label, inline=True)
        embed.add_field(
            name="Stack rewards",
            value="yes" if cfg.get("stack") else "no",
            inline=True,
        )
        embed.add_field(
            name="Multiplier",
            value=f"{float(cfg.get('multiplier') or 1):.2f}",
            inline=True,
        )
        embed.add_field(
            name="Booster multi",
            value=f"{float(cfg.get('booster') or 1):.2f}",
            inline=True,
        )
        embed.add_field(
            name="Message",
            value=f"```\n{(cfg.get('message') or 'n/a')[:500]}\n```",
            inline=False,
        )
        return await ctx.send(embed=embed)

    # rewards -----------------------------------------------------------

    @leveling.group(
        name="rewards",
        description="Manage level role rewards",
        invoke_without_command=True,
        example=",leveling rewards list",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards(self, ctx):
        return await ctx.send_help(ctx.command)

    @leveling_rewards.command(
        name="add",
        description="Assign a role reward at a level",
        example=",leveling rewards add 10 @Member",
        usage="<level> <role>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_add(self, ctx, level: int, role: Role):
        if not await self._require_enabled(ctx):
            return
        if level < 1:
            return await ctx.warn("Level must be at least **1**")
        existing = await self.db.fetchrow(
            "SELECT level FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        if existing:
            return await ctx.warn(
                f"{role.mention} is already a reward for **Level {existing['level']}**"
            )
        await self.db.execute(
            "INSERT INTO level_rewards (guild_id, level, role_id) VALUES ($1, $2, $3)",
            ctx.guild.id,
            level,
            role.id,
        )
        return await ctx.success(
            f"Added {role.mention} as a reward for **Level {level}**"
        )

    @leveling_rewards.command(
        name="remove",
        description="Remove a role reward",
        example=",leveling rewards remove @Member",
        usage="<role>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_remove(self, ctx, role: Role):
        if not await self._require_enabled(ctx):
            return
        row = await self.db.fetchrow(
            "SELECT level FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        if not row:
            return await ctx.warn(f"{role.mention} is not a level reward")
        await self.db.execute(
            "DELETE FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        return await ctx.success(
            f"Removed reward for **Level {row['level']}**"
        )

    @leveling_rewards.command(
        name="list",
        description="List all level rewards",
        example=",leveling rewards list",
    )
    async def leveling_rewards_list(self, ctx):
        rows = await self.db.fetch(
            "SELECT role_id, level FROM level_rewards WHERE guild_id = $1 ORDER BY level",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No level rewards configured")
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            label = role.mention if role else f"`{r['role_id']}`"
            lines.append(f"{label} — **Level {r['level']}**")
        return await ctx.paginate(Embed(title="Level Rewards"), lines)

    @leveling_rewards.command(
        name="stack",
        description="Toggle stacking all reward roles vs highest only",
        example=",leveling rewards stack on",
        usage="<on|off>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_stack(self, ctx, option: str):
        if not await self._require_enabled(ctx):
            return
        opt = option.strip().lower()
        if opt not in {"on", "off", "true", "false", "yes", "no", "1", "0"}:
            return await ctx.warn("Use **on** or **off**")
        enabled = opt in {"on", "true", "yes", "1"}
        await self.db.execute(
            "UPDATE leveling SET stack = $1 WHERE guild_id = $2",
            enabled,
            ctx.guild.id,
        )
        return await ctx.success(
            f"{'Enabled' if enabled else 'Disabled'} stacking rewards"
        )

    # ignore ------------------------------------------------------------

    @leveling.group(
        name="ignore",
        description="Ignore users/roles/channels for XP",
        invoke_without_command=True,
        example=",leveling ignore add #bots",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore(self, ctx):
        return await ctx.send_help(ctx.command)

    async def _update_ignore(
        self, ctx, column: str, item_id: int, *, add: bool, mention: str
    ):
        cfg = await self._require_enabled(ctx)
        if not cfg:
            return
        current = self._parse_json_list(cfg.get(column))
        if add:
            if item_id in current:
                return await ctx.warn(f"{mention} is already ignored")
            current.append(item_id)
            msg = f"Added {mention} to the ignore list"
        else:
            if item_id not in current:
                return await ctx.warn(f"{mention} is not ignored")
            current.remove(item_id)
            msg = f"Removed {mention} from the ignore list"
        await self.db.execute(
            f"UPDATE leveling SET {column} = $1 WHERE guild_id = $2",
            json.dumps(current),
            ctx.guild.id,
        )
        return await ctx.success(msg)

    @leveling_ignore.command(
        name="add",
        description="Ignore a user, role, or channel for XP",
        example=",leveling ignore add #bots",
        usage="<user|role|channel>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_add(
        self, ctx, target: Union[Member, User, Role, TextChannel]
    ):
        if isinstance(target, (Member, User)):
            return await self._update_ignore(
                ctx, "users", target.id, add=True, mention=target.mention
            )
        if isinstance(target, Role):
            return await self._update_ignore(
                ctx, "roles", target.id, add=True, mention=target.mention
            )
        return await self._update_ignore(
            ctx, "channels", target.id, add=True, mention=target.mention
        )

    @leveling_ignore.command(
        name="remove",
        description="Remove someone from the XP ignore list",
        example=",leveling ignore remove #bots",
        usage="<user|role|channel>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_remove(
        self, ctx, target: Union[Member, User, Role, TextChannel]
    ):
        if isinstance(target, (Member, User)):
            return await self._update_ignore(
                ctx, "users", target.id, add=False, mention=target.mention
            )
        if isinstance(target, Role):
            return await self._update_ignore(
                ctx, "roles", target.id, add=False, mention=target.mention
            )
        return await self._update_ignore(
            ctx, "channels", target.id, add=False, mention=target.mention
        )

    @leveling_ignore.command(
        name="list",
        description="View the XP ignore list",
        example=",leveling ignore list",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_list(self, ctx):
        cfg = await self._require_enabled(ctx)
        if not cfg:
            return
        lines = []
        for uid in self._parse_json_list(cfg.get("users")):
            lines.append(f"<@{uid}>")
        for rid in self._parse_json_list(cfg.get("roles")):
            lines.append(f"<@&{rid}>")
        for cid in self._parse_json_list(cfg.get("channels")):
            lines.append(f"<#{cid}>")
        if not lines:
            return await ctx.warn("Nothing is ignored for XP")
        return await ctx.paginate(Embed(title="Level Ignore List"), lines)

    # role sync ---------------------------------------------------------

    async def _sync_user_roles(self, guild, member: Member, user_level: int) -> None:
        cfg = await self._get_cfg(guild.id)
        if not cfg:
            return
        rewards = await self.db.fetch(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = $1",
            guild.id,
        )
        if not rewards:
            return
        by_level: dict[int, list[int]] = {}
        for r in rewards:
            by_level.setdefault(int(r["level"]), []).append(int(r["role_id"]))
        stack = bool(cfg.get("stack"))
        if stack:
            to_add = []
            for lv, role_ids in by_level.items():
                if lv <= user_level:
                    for rid in role_ids:
                        role = guild.get_role(rid)
                        if role and role not in member.roles:
                            to_add.append(role)
            if to_add:
                with contextlib.suppress(HTTPException, discord.Forbidden):
                    await member.add_roles(*to_add, reason="Level reward sync")
        else:
            eligible = [lv for lv in by_level if lv <= user_level]
            if not eligible:
                return
            highest = max(eligible)
            keep = by_level[highest][0]
            keep_role = guild.get_role(keep)
            remove = []
            for lv, role_ids in by_level.items():
                if lv == highest:
                    continue
                for rid in role_ids:
                    role = guild.get_role(rid)
                    if role and role in member.roles:
                        remove.append(role)
            if remove:
                with contextlib.suppress(HTTPException, discord.Forbidden):
                    await member.remove_roles(*remove, reason="Level reward sync")
            if keep_role and keep_role not in member.roles:
                with contextlib.suppress(HTTPException, discord.Forbidden):
                    await member.add_roles(keep_role, reason="Level reward sync")


async def setup(bot) -> None:
    await bot.add_cog(Leveling(bot))
