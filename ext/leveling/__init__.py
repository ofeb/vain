from __future__ import annotations

import asyncio
import contextlib
import io
import json
import math
from collections import defaultdict
from typing import Optional, Union

import discord
from discord import (
    Embed,
    File,
    HTTPException,
    Interaction,
    Member,
    Message,
    Role,
    TextChannel,
    User,
)
from discord.ext.commands import Author, BucketType, cooldown, group, command
from discord.ui import Button, View

from asyncpg import UniqueViolationError
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from core.discord.package import Package
from core.managers.permissions import has_permissions


# ─────────────────────────────────────────────────────────────
# Rank card (Pillow)
# ─────────────────────────────────────────────────────────────

FONT_BOLD = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Bold.ttf"
FONT_SEMI = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-SemiBold.ttf"
FONT_MED = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Medium.ttf"
FONT_REG = "/usr/share/fonts/SlidesCarnival/google/Inter/static/Inter_18pt-Regular.ttf"
FONT_POPPINS_BOLD = "/usr/share/fonts/SlidesCarnival/google/Poppins/Poppins-Bold.ttf"


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _rounded_rectangle(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill=None,
    outline=None,
    width: int = 1,
):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline, width=width)


def _circular_avatar(avatar: Image.Image, size: int = 140) -> Image.Image:
    avatar = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(avatar, (0, 0), mask)
    return output


def _draw_progress_ring(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    radius: int,
    progress: float,
    width: int = 8,
    bg_color: tuple = (40, 40, 55, 255),
    fg_color: tuple = (88, 101, 242, 255),
):
    """Draw a circular progress ring (0.0 – 1.0)."""
    # background ring
    bbox = [
        center[0] - radius,
        center[1] - radius,
        center[0] + radius,
        center[1] + radius,
    ]
    draw.arc(bbox, start=0, end=360, fill=bg_color, width=width)
    if progress > 0:
        # Discord-style: start from top, go clockwise
        start = -90
        end = start + (360 * min(max(progress, 0.0), 1.0))
        draw.arc(bbox, start=start, end=end, fill=fg_color, width=width)


async def generate_rank_card(
    member: Member,
    level: int,
    xp: int,
    target_xp: int,
    rank: int,
    total_members: int,
) -> io.BytesIO:
    """
    High-quality horizontal rank card.
    Size: 934 × 282 (classic Discord rank-card ratio).
    """
    W, H = 934, 282
    progress = min(xp / target_xp, 1.0) if target_xp > 0 else 0.0

    # base canvas
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)

    # dark glass background
    _rounded_rectangle(draw, (0, 0, W - 1, H - 1), radius=24, fill=(22, 22, 32, 255))

    # subtle left accent bar
    _rounded_rectangle(draw, (0, 0, 8, H - 1), radius=4, fill=(88, 101, 242, 255))

    # fetch & process avatar
    try:
        avatar_bytes = await member.display_avatar.read()
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    except Exception:
        avatar_img = Image.new("RGBA", (180, 180), (60, 60, 80, 255))

    avatar_size = 148
    avatar = _circular_avatar(avatar_img, avatar_size)

    # progress ring around avatar
    ring_cx, ring_cy = 100, H // 2
    ring_radius = 82
    # draw ring on a temporary layer for better quality
    ring_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring_layer)
    _draw_progress_ring(
        ring_draw,
        (ring_cx, ring_cy),
        ring_radius,
        progress,
        width=9,
        bg_color=(45, 45, 60, 255),
        fg_color=(88, 101, 242, 255),
    )
    base = Image.alpha_composite(base, ring_layer)
    draw = ImageDraw.Draw(base)

    # paste avatar
    avatar_pos = (ring_cx - avatar_size // 2, ring_cy - avatar_size // 2)
    base.paste(avatar, avatar_pos, avatar)

    # fonts
    font_name = _load_font(FONT_BOLD, 32)
    font_level = _load_font(FONT_POPPINS_BOLD, 48)
    font_label = _load_font(FONT_MED, 18)
    font_small = _load_font(FONT_REG, 16)
    font_xp = _load_font(FONT_SEMI, 18)
    font_rank = _load_font(FONT_BOLD, 22)

    # username
    name = member.display_name
    if len(name) > 18:
        name = name[:17] + "…"
    draw.text((210, 48), name, font=font_name, fill=(245, 245, 250, 255))

    # rank text
    rank_text = f"RANK #{rank}"
    draw.text((210, 92), rank_text, font=font_rank, fill=(160, 160, 180, 255))

    # level badge (right side)
    level_label = "LEVEL"
    level_value = str(level)
    # measure
    lvl_w = draw.textlength(level_value, font=font_level)
    draw.text((W - 60 - lvl_w, 40), level_value, font=font_level, fill=(255, 255, 255, 255))
    draw.text((W - 60 - draw.textlength(level_label, font=font_label), 95), level_label, font=font_label, fill=(140, 140, 160, 255))

    # XP bar background
    bar_x, bar_y = 210, 175
    bar_w, bar_h = 560, 22
    _rounded_rectangle(
        draw,
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=11,
        fill=(40, 40, 55, 255),
    )

    # XP bar fill
    fill_w = max(int(bar_w * progress), 8 if progress > 0 else 0)
    if fill_w > 0:
        # soft gradient fill using a temporary image
        fill_img = Image.new("RGBA", (fill_w, bar_h), (0, 0, 0, 0))
        fill_draw = ImageDraw.Draw(fill_img)
        for i in range(fill_w):
            # blue → indigo gradient
            r = int(88 + (114 - 88) * (i / max(fill_w, 1)))
            g = int(101 + (137 - 101) * (i / max(fill_w, 1)))
            b = int(242 + (218 - 242) * (i / max(fill_w, 1)))
            fill_draw.line([(i, 0), (i, bar_h)], fill=(r, g, b, 255))
        # mask to rounded
        mask = Image.new("L", (fill_w, bar_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, fill_w - 1, bar_h - 1], radius=11, fill=255)
        base.paste(fill_img, (bar_x, bar_y), mask)

    # XP text under bar
    xp_text = f"{xp:,}  /  {target_xp:,} XP"
    pct_text = f"{progress * 100:.1f}%"
    draw.text((bar_x, bar_y + 32), xp_text, font=font_xp, fill=(180, 180, 200, 255))
    pct_w = draw.textlength(pct_text, font=font_xp)
    draw.text((bar_x + bar_w - pct_w, bar_y + 32), pct_text, font=font_xp, fill=(140, 140, 170, 255))

    # total members hint
    total_text = f"of {total_members:,} members"
    draw.text((210, 240), total_text, font=font_small, fill=(110, 110, 130, 255))

    # final soft vignette / polish
    output = base.convert("RGB")
    buf = io.BytesIO()
    output.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────
# Confirmation view (simple)
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Leveling Package
# ─────────────────────────────────────────────────────────────

class Leveling(Package):
    """Server leveling, rank cards, multipliers & role rewards."""

    def __init__(self, bot):
        super().__init__(bot)
        self.description = "Leveling system with rank cards, multipliers and rewards"
        self._xp_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ── helpers ──────────────────────────────────────────────

    async def level_replace(self, member: Member, params: str) -> str:
        row = await self.db.fetchrow(
            "SELECT level, target_xp FROM level_user WHERE guild_id = $1 AND user_id = $2",
            member.guild.id,
            member.id,
        )
        if not row:
            params = params.replace("{level}", "1").replace("{target_xp}", "100")
            return params
        return (
            params.replace("{level}", str(row["level"]))
            .replace("{target_xp}", str(row["target_xp"]))
        )

    def _calc_target(self, level: int) -> int:
        return max(int((100 * level + 1) ** 0.9), 50)

    def _total_xp(self, level: int, current_xp: float) -> int:
        total = 0
        for lvl in range(1, level):
            total += self._calc_target(lvl)
        return total + int(current_xp)

    async def _update_blacklist(
        self, ctx, column: str, item_id: int, add: bool
    ) -> Message:
        raw = await self.db.fetchval(
            f"SELECT {column} FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        current = json.loads(raw) if raw else []

        if column == "roles":
            obj = ctx.guild.get_role(item_id)
            mention = obj.mention if obj else str(item_id)
            label = "role"
        elif column == "channels":
            obj = ctx.guild.get_channel(item_id)
            mention = obj.mention if obj else str(item_id)
            label = "channel"
        else:
            obj = ctx.guild.get_member(item_id) or await self.bot.fetch_user(item_id)
            mention = obj.mention if obj else str(item_id)
            label = "user"

        if add:
            if item_id in current:
                return await ctx.warn(f"That {label} is already on the ignore list")
            current.append(item_id)
            msg = f"Added {label} {mention} to the XP ignore list"
        else:
            if item_id not in current:
                return await ctx.warn(f"That {label} is not on the ignore list")
            current.remove(item_id)
            msg = f"Removed {label} {mention} from the XP ignore list"

        await self.db.execute(
            f"UPDATE leveling SET {column} = $1 WHERE guild_id = $2",
            json.dumps(current),
            ctx.guild.id,
        )
        return await ctx.success(msg)

    async def _sync_roles(self, guild: discord.Guild, member: Member, user_level: int):
        stack = await self.db.fetchval(
            "SELECT stack FROM leveling WHERE guild_id = $1", guild.id
        )
        rewards = await self.db.fetch(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = $1", guild.id
        )
        if not rewards:
            return

        by_level: dict[int, list[int]] = {}
        for r in rewards:
            by_level.setdefault(r["level"], []).append(r["role_id"])

        min_lvl = min(by_level.keys()) if by_level else None
        if min_lvl is None:
            return

        if user_level < min_lvl:
            to_remove = [
                guild.get_role(rid)
                for rids in by_level.values()
                for rid in rids
                if (role := guild.get_role(rid)) and role in member.roles
            ]
            if to_remove:
                with contextlib.suppress(HTTPException):
                    await member.remove_roles(*to_remove, reason="Level rewards (below minimum)")
            return

        if stack:
            to_add = [
                guild.get_role(rid)
                for lvl, rids in by_level.items()
                if lvl <= user_level
                for rid in rids
                if (role := guild.get_role(rid)) and role not in member.roles
            ]
            if to_add:
                with contextlib.suppress(HTTPException):
                    await member.add_roles(*to_add, reason="Level reward stack")
        else:
            highest = max((lvl for lvl in by_level if lvl <= user_level), default=None)
            if highest is None:
                return
            highest_role = guild.get_role(by_level[highest][0])
            # remove lower
            to_remove = [
                guild.get_role(rid)
                for lvl, rids in by_level.items()
                if lvl < highest
                for rid in rids
                if (role := guild.get_role(rid)) and role in member.roles
            ]
            if to_remove:
                with contextlib.suppress(HTTPException):
                    await member.remove_roles(*to_remove, reason="Level reward replace")
            if highest_role and highest_role not in member.roles:
                with contextlib.suppress(HTTPException):
                    await member.add_roles(highest_role, reason="Level reward")

    # ── rank / level card ────────────────────────────────────

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

        sorted_rows = sorted(rows, key=lambda r: (r["level"], r["xp"]), reverse=True)
        position = next(
            (i + 1 for i, r in enumerate(sorted_rows) if r["user_id"] == member.id),
            None,
        )
        if position is None:
            return await ctx.warn(f"{member.mention} has no recorded level data")

        data = next(r for r in sorted_rows if r["user_id"] == member.id)
        total = len(sorted_rows)

        card = await generate_rank_card(
            member=member if isinstance(member, Member) else ctx.author,
            level=data["level"],
            xp=int(data["xp"]),
            target_xp=int(data["target_xp"]),
            rank=position,
            total_members=total,
        )
        file = File(card, filename=f"rank-{member.id}.png")
        return await ctx.send(file=file)

    # ── main group ───────────────────────────────────────────

    @group(
        name="leveling",
        aliases=["lvlsys", "levels"],
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
        exists = await self.db.fetchrow(
            "SELECT 1 FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        if exists:
            return await ctx.warn("Leveling is already enabled")
        await self.db.execute(
            """INSERT INTO leveling (guild_id, message, multiplier, booster, stack, command)
               VALUES ($1, $2, 1.0, 1.0, false, false)""",
            ctx.guild.id,
            "Nice work {user.mention} — you reached **Level {level}**!",
        )
        return await ctx.success("Leveling system is now **enabled**")

    @leveling.command(
        name="disable",
        description="Turn off leveling and wipe all progress (confirmation required)",
        example=",leveling disable",
    )
    @has_permissions(manage_guild=True)
    async def leveling_disable(self, ctx):
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send(
            "This will **delete every user's XP & level data** for this server. Continue?",
            view=view,
        )
        await view.wait()
        if view.value is True:
            await self.db.execute("DELETE FROM leveling WHERE guild_id = $1", ctx.guild.id)
            await self.db.execute("DELETE FROM level_user WHERE guild_id = $1", ctx.guild.id)
            await msg.edit(content="Leveling system disabled and all data cleared.", view=None)
        else:
            await msg.edit(content="Cancelled.", view=None)

    @leveling.command(
        name="channel",
        description="Set where level-up messages are sent (`any`, `dm`, or a channel)",
        example=",leveling channel #levels",
        usage="<any | dm | channel>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_channel(self, ctx, *, target: Union[TextChannel, str]):
        if isinstance(target, str):
            low = target.lower()
            if low == "any":
                await self.db.execute(
                    "UPDATE leveling SET channel_id = NULL WHERE guild_id = $1",
                    ctx.guild.id,
                )
                return await ctx.success("Level-up messages will appear in **any** channel")
            if low == "dm":
                await self.db.execute(
                    "UPDATE leveling SET channel_id = 0 WHERE guild_id = $1",
                    ctx.guild.id,
                )
                return await ctx.success("Level-up messages will be sent via **DM**")
            return await ctx.warn("Use `any`, `dm`, or a channel mention")

        await self.db.execute(
            "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
            target.id,
            ctx.guild.id,
        )
        return await ctx.success(f"Level-up messages will be sent in {target.mention}")

    @leveling.command(
        name="message",
        description="Set the custom level-up message (supports {user}, {level}, {target_xp})",
        example=",leveling message Nice one {user.mention}! Level {level}",
        usage="<message | none>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_message(self, ctx, *, message: str = "Nice work {user.mention} — you reached **Level {level}**!"):
        if message.lower().strip() == "none":
            await self.db.execute(
                "UPDATE leveling SET message = 'none' WHERE guild_id = $1",
                ctx.guild.id,
            )
            return await ctx.success("Level-up messages have been **disabled**")
        await self.db.execute(
            "UPDATE leveling SET message = $1 WHERE guild_id = $2",
            message,
            ctx.guild.id,
        )
        return await ctx.success(f"Level-up message updated:\n```{message}```")

    @leveling.command(
        name="test",
        description="Preview the current level-up message",
        example=",leveling test",
    )
    @has_permissions(manage_guild=True)
    async def leveling_test(self, ctx):
        row = await self.db.fetchrow(
            "SELECT * FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        if not row:
            return await ctx.warn("Leveling is not configured")
        channel = ctx.guild.get_channel(row["channel_id"]) if row["channel_id"] else ctx.channel
        if row["channel_id"] == 0:
            channel = ctx.author  # dm
        script = await self.level_replace(ctx.author, row["message"])
        # simple send (no full embed builder here)
        try:
            if isinstance(channel, (TextChannel, discord.DMChannel)) or hasattr(channel, "send"):
                m = await channel.send(script.replace("{user}", ctx.author.mention).replace("{user.mention}", ctx.author.mention))
                return await ctx.success(f"Preview sent → {m.jump_url}")
            return await ctx.warn("Could not resolve the target channel")
        except Exception as e:
            return await ctx.warn(f"Failed to send preview: `{e}`")

    # ── multipliers ──────────────────────────────────────────

    @leveling.command(
        name="multiplier",
        description="Set the global XP multiplier (0.25 – 3.00 in 0.25 steps)",
        example=",leveling multiplier 1.5",
        usage="<0.25–3.00>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_multiplier(self, ctx, value: float):
        allowed = {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0}
        if value not in allowed:
            return await ctx.warn(
                "Multiplier must be one of: `0.25 0.5 0.75 1 1.25 1.5 1.75 2 2.25 2.5 2.75 3`"
            )
        await self.db.execute(
            "UPDATE leveling SET multiplier = $1 WHERE guild_id = $2",
            value,
            ctx.guild.id,
        )
        return await ctx.success(f"Global multiplier set to **{value:.2f}×**")

    @leveling.command(
        name="booster",
        description="Set the XP multiplier for server boosters",
        example=",leveling booster 2",
        usage="<0.25–3.00>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_booster(self, ctx, value: float):
        allowed = {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0}
        if value not in allowed:
            return await ctx.warn(
                "Multiplier must be one of: `0.25 0.5 0.75 1 1.25 1.5 1.75 2 2.25 2.5 2.75 3`"
            )
        await self.db.execute(
            "UPDATE leveling SET booster = $1 WHERE guild_id = $2",
            value,
            ctx.guild.id,
        )
        return await ctx.success(f"Booster multiplier set to **{value:.2f}×**")

    @leveling.group(
        name="rolemultiplier",
        aliases=["rmulti"],
        description="Manage per-role XP multipliers",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def leveling_rolemulti(self, ctx):
        return await ctx.send_help()

    @leveling_rolemulti.command(
        name="add",
        description="Add or update a role XP multiplier",
        example=",leveling rolemultiplier add @VIP 2",
        usage="<role> <0.25–3.00>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rolemulti_add(self, ctx, role: Role, value: float):
        allowed = {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0}
        if value not in allowed:
            return await ctx.warn("Invalid multiplier value")
        await self.db.execute(
            """INSERT INTO level_multiplier (guild_id, role_id, multiplier)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, role_id) DO UPDATE SET multiplier = $3""",
            ctx.guild.id,
            role.id,
            value,
        )
        return await ctx.success(f"Role {role.mention} now grants **{value:.2f}×** XP")

    @leveling_rolemulti.command(
        name="remove",
        description="Remove a role XP multiplier",
        example=",leveling rolemultiplier remove @VIP",
        usage="<role>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rolemulti_remove(self, ctx, role: Role):
        deleted = await self.db.execute(
            "DELETE FROM level_multiplier WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        if deleted == "DELETE 0":
            return await ctx.warn(f"No multiplier set for {role.mention}")
        return await ctx.success(f"Removed multiplier for {role.mention}")

    # ── voice multipliers ────────────────────────────────────

    @leveling.group(
        name="voice",
        description="Voice-channel XP multipliers",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def leveling_voice(self, ctx):
        return await ctx.send_help()

    @leveling_voice.command(
        name="multiplier",
        description="Global voice XP multiplier",
        example=",leveling voice multiplier 1.5",
    )
    @has_permissions(manage_guild=True)
    async def leveling_voice_multiplier(self, ctx, value: float):
        allowed = {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0}
        if value not in allowed:
            return await ctx.warn("Invalid multiplier")
        await self.db.execute(
            "UPDATE leveling SET voice_multiplier = $1 WHERE guild_id = $2",
            value,
            ctx.guild.id,
        )
        return await ctx.success(f"Voice multiplier set to **{value:.2f}×**")

    @leveling_voice.command(
        name="booster",
        description="Voice XP multiplier for boosters",
        example=",leveling voice booster 2",
    )
    @has_permissions(manage_guild=True)
    async def leveling_voice_booster(self, ctx, value: float):
        allowed = {0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0}
        if value not in allowed:
            return await ctx.warn("Invalid multiplier")
        await self.db.execute(
            "UPDATE leveling SET voice_booster = $1 WHERE guild_id = $2",
            value,
            ctx.guild.id,
        )
        return await ctx.success(f"Voice booster multiplier set to **{value:.2f}×**")

    # ── view multipliers ─────────────────────────────────────

    @leveling.command(
        name="multipliers",
        aliases=["multis"],
        description="Show all active multipliers for this server",
        example=",leveling multipliers",
    )
    async def leveling_multipliers(self, ctx):
        row = await self.db.fetchrow(
            "SELECT * FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        if not row:
            return await ctx.warn("Leveling is not enabled")

        global_m = row.get("multiplier") or 1.0
        booster_m = row.get("booster") or 1.0
        voice_m = row.get("voice_multiplier") or 1.0
        voice_b = row.get("voice_booster") or 1.0

        role_ms = await self.db.fetch(
            "SELECT role_id, multiplier FROM level_multiplier WHERE guild_id = $1",
            ctx.guild.id,
        )
        role_voice_ms = await self.db.fetch(
            "SELECT role_id, multiplier FROM level_multiplier_voice WHERE guild_id = $1",
            ctx.guild.id,
        )

        embed = Embed(title="XP Multipliers", color=0x5865F2)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.add_field(name="Global", value=f"**{global_m:.2f}×**", inline=True)
        embed.add_field(name="Booster", value=f"**{booster_m:.2f}×**", inline=True)
        embed.add_field(name="Voice", value=f"**{voice_m:.2f}×**", inline=True)
        embed.add_field(name="Voice Booster", value=f"**{voice_b:.2f}×**", inline=True)

        if role_ms:
            lines = []
            for r in role_ms:
                role = ctx.guild.get_role(r["role_id"])
                lines.append(f"{role.mention if role else r['role_id']} — **{r['multiplier']:.2f}×**")
            embed.add_field(name="Role Multipliers", value="\n".join(lines) or "None", inline=False)
        else:
            embed.add_field(name="Role Multipliers", value="None", inline=False)

        if role_voice_ms:
            lines = []
            for r in role_voice_ms:
                role = ctx.guild.get_role(r["role_id"])
                lines.append(f"{role.mention if role else r['role_id']} — **{r['multiplier']:.2f}×**")
            embed.add_field(name="Voice Role Multipliers", value="\n".join(lines), inline=False)

        return await ctx.send(embed=embed)

    # ── config / set / reset ─────────────────────────────────

    @leveling.command(
        name="config",
        aliases=["settings", "status"],
        description="View the current leveling configuration",
        example=",leveling config",
    )
    @has_permissions(manage_guild=True)
    async def leveling_config(self, ctx):
        row = await self.db.fetchrow(
            "SELECT * FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        if not row:
            return await ctx.warn("Leveling is not enabled")

        ch = ctx.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        ch_text = ch.mention if ch else ("DM" if row["channel_id"] == 0 else "Any channel")

        embed = Embed(title=f"{ctx.guild.name} — Leveling Config", color=0x5865F2)
        embed.add_field(name="Channel", value=ch_text, inline=True)
        embed.add_field(name="Stack Rewards", value="Yes" if row.get("stack") else "No", inline=True)
        embed.add_field(name="Ignore Commands", value="Yes" if row.get("command") else "No", inline=True)
        embed.add_field(name="Message", value=f"```{row['message'][:200]}```", inline=False)
        return await ctx.send(embed=embed)

    @leveling.command(
        name="set",
        description="Manually set a member's level",
        example=",leveling set @user 25",
        usage="<member> <level>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_set(self, ctx, member: Member, level: int):
        if level < 1 or level > 1000:
            return await ctx.warn("Level must be between **1** and **1000**")
        target = self._calc_target(level)
        exists = await self.db.fetchrow(
            "SELECT 1 FROM level_user WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            member.id,
        )
        if exists:
            await self.db.execute(
                """UPDATE level_user
                   SET xp = 0, target_xp = $1, level = $2
                   WHERE guild_id = $3 AND user_id = $4""",
                target,
                level,
                ctx.guild.id,
                member.id,
            )
        else:
            await self.db.execute(
                "INSERT INTO level_user (guild_id, user_id, xp, level, target_xp) VALUES ($1,$2,0,$3,$4)",
                ctx.guild.id,
                member.id,
                level,
                target,
            )
        await self._sync_roles(ctx.guild, member, level)
        return await ctx.success(f"Set {member.mention} to **Level {level}**")

    @leveling.command(
        name="reset",
        description="Reset a member's (or everyone's) level data",
        example=",leveling reset @user",
        usage="[member]",
    )
    @has_permissions(manage_guild=True)
    async def leveling_reset(self, ctx, member: Optional[Member] = None):
        view = ConfirmView(ctx.author.id)
        if member is None:
            prompt = "Reset **everyone's** level data in this server?"
        else:
            prompt = f"Reset level data for {member.mention}?"

        msg = await ctx.send(prompt, view=view)
        await view.wait()
        if view.value is not True:
            return await msg.edit(content="Cancelled.", view=None)

        if member is None:
            await self.db.execute("DELETE FROM level_user WHERE guild_id = $1", ctx.guild.id)
            await msg.edit(content="All level data has been wiped.", view=None)
        else:
            await self.db.execute(
                "DELETE FROM level_user WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                member.id,
            )
            await msg.edit(content=f"Reset level data for {member.mention}.", view=None)

    # ── leaderboard ──────────────────────────────────────────

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

        sorted_rows = sorted(filtered, key=lambda r: (r["level"], r["xp"]), reverse=True)[:50]
        lines = []
        for i, r in enumerate(sorted_rows, 1):
            user = self.bot.get_user(r["user_id"]) or r["user_id"]
            lines.append(
                f"`#{i:02}` **{user}** — Level **{r['level']}** "
                f"(`{int(r['xp']):,}` / `{int(r['target_xp']):,}` XP)"
            )

        # simple paginate via embeds if many lines
        embed = Embed(
            title="Level Leaderboard",
            description="\n".join(lines[:15]),
            color=0x5865F2,
        )
        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None,
        )
        embed.set_footer(text=f"Showing top {min(15, len(lines))} of {len(sorted_rows)}")
        return await ctx.send(embed=embed)

    # ── rewards ──────────────────────────────────────────────

    @leveling.group(
        name="rewards",
        description="Manage level role rewards",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards(self, ctx):
        return await ctx.send_help()

    @leveling_rewards.command(
        name="add",
        description="Assign a role reward for reaching a level",
        example=",leveling rewards add 10 @Member",
        usage="<level> <role>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_add(self, ctx, level: int, role: Role):
        if level < 1:
            return await ctx.warn("Level must be at least 1")
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
            f"{role.mention} will now be given at **Level {level}**"
        )

    @leveling_rewards.command(
        name="remove",
        description="Remove a role from the reward list",
        example=",leveling rewards remove @Member",
        usage="<role>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_remove(self, ctx, role: Role):
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
            f"Removed {role.mention} (was Level {row['level']} reward)"
        )

    @leveling_rewards.command(
        name="list",
        description="List all level role rewards",
        example=",leveling rewards list",
    )
    async def leveling_rewards_list(self, ctx):
        rows = await self.db.fetch(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = $1 ORDER BY level",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No level rewards configured")
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            lines.append(f"**Level {r['level']}** → {role.mention if role else r['role_id']}")
        embed = Embed(title="Level Rewards", description="\n".join(lines), color=0x5865F2)
        return await ctx.send(embed=embed)

    @leveling_rewards.command(
        name="stack",
        description="Toggle whether members keep previous reward roles",
        example=",leveling rewards stack on",
        usage="<on | off>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_stack(self, ctx, option: str):
        option = option.lower()
        if option not in ("on", "off"):
            return await ctx.warn("Use `on` or `off`")
        await self.db.execute(
            "UPDATE leveling SET stack = $1 WHERE guild_id = $2",
            option == "on",
            ctx.guild.id,
        )
        return await ctx.success(
            f"Reward stacking is now **{'enabled' if option == 'on' else 'disabled'}**"
        )

    @leveling_rewards.command(
        name="sync",
        description="Re-apply all reward roles based on current levels (rate-limited)",
        example=",leveling rewards sync",
    )
    @has_permissions(manage_guild=True)
    @cooldown(1, 3600, BucketType.guild)
    async def leveling_rewards_sync(self, ctx):
        rewards = await self.db.fetch(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = $1", ctx.guild.id
        )
        if not rewards:
            return await ctx.warn("No rewards to sync")
        users = await self.db.fetch(
            "SELECT user_id, level FROM level_user WHERE guild_id = $1", ctx.guild.id
        )
        if not users:
            return await ctx.warn("No user data found")

        status = await ctx.send("Syncing roles… this may take a moment.")
        for i, u in enumerate(users):
            member = ctx.guild.get_member(u["user_id"])
            if member:
                await self._sync_roles(ctx.guild, member, u["level"])
            if i % 10 == 0:
                await asyncio.sleep(1.2)
        await status.edit(content="All reward roles have been synchronized.")

    # ── ignore list ──────────────────────────────────────────

    @leveling.group(
        name="ignore",
        description="Manage users / roles / channels that should not gain XP",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore(self, ctx):
        return await ctx.send_help()

    @leveling_ignore.command(
        name="add",
        description="Add a user, role or channel to the XP ignore list",
        example=",leveling ignore add #bots",
        usage="<user | role | channel>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_add(
        self, ctx, target: Union[Member, User, Role, TextChannel]
    ):
        if isinstance(target, (Member, User)):
            return await self._update_blacklist(ctx, "users", target.id, add=True)
        if isinstance(target, Role):
            return await self._update_blacklist(ctx, "roles", target.id, add=True)
        if isinstance(target, TextChannel):
            return await self._update_blacklist(ctx, "channels", target.id, add=True)

    @leveling_ignore.command(
        name="remove",
        description="Remove a user, role or channel from the XP ignore list",
        example=",leveling ignore remove #bots",
        usage="<user | role | channel>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_remove(
        self, ctx, target: Union[Member, User, Role, TextChannel]
    ):
        if isinstance(target, (Member, User)):
            return await self._update_blacklist(ctx, "users", target.id, add=False)
        if isinstance(target, Role):
            return await self._update_blacklist(ctx, "roles", target.id, add=False)
        if isinstance(target, TextChannel):
            return await self._update_blacklist(ctx, "channels", target.id, add=False)

    @leveling_ignore.command(
        name="list",
        description="Show everything currently ignored for XP",
        example=",leveling ignore list",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_list(self, ctx):
        content = []
        for col, prefix in (("users", "<@"), ("roles", "<@&"), ("channels", "<#")):
            raw = await self.db.fetchval(
                f"SELECT {col} FROM leveling WHERE guild_id = $1", ctx.guild.id
            )
            items = json.loads(raw) if raw else []
            content.extend(f"{prefix}{i}>" for i in items)
        if not content:
            return await ctx.warn("The ignore list is empty")
        embed = Embed(
            title="XP Ignore List",
            description="\n".join(content[:40]),
            color=0x5865F2,
        )
        return await ctx.send(embed=embed)

    @leveling_ignore.command(
        name="commands",
        description="Toggle whether bot commands grant XP",
        example=",leveling ignore commands on",
        usage="<on | off>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_ignore_commands(self, ctx, option: str):
        option = option.lower()
        if option not in ("on", "off"):
            return await ctx.warn("Use `on` or `off`")
        await self.db.execute(
            "UPDATE leveling SET command = $1 WHERE guild_id = $2",
            option == "on",
            ctx.guild.id,
        )
        return await ctx.success(
            f"Commands are now **{'ignored' if option == 'on' else 'counted'}** for XP"
        )


async def setup(bot) -> None:
    await bot.add_cog(Leveling(bot))
