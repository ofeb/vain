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
from PIL import Image, ImageDraw, ImageFont

from config import color as bot_color
from core.discord.mixin import _Meta
from core.discord.package import Package
from core.managers.permissions import has_permissions

from .events import LevelingEvents


_FONT_BOLD = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_FONT_REG = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

_VALID_MULTIS = (
    0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0,
)


_CARD_BG = (22, 24, 32, 255)
_CARD_PANEL = (32, 34, 44, 255)
_TRACK = (48, 50, 62, 255)
_TEXT = (245, 246, 250, 255)
_MUTED = (158, 162, 178, 255)
_SOFT = (190, 194, 210, 255)


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (_FONT_BOLD if bold else _FONT_REG):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    
    if bold:
        for path in _FONT_REG:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _hex_rgb(value: int) -> tuple[int, int, int]:
    value = int(value) & 0xFFFFFF
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    try:
        return float(draw.textlength(text, font=font))
    except Exception:
        box = draw.textbbox((0, 0), text, font=font)
        return float(box[2] - box[0])


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: float,
) -> str:
    text = (text or "").strip() or "User"
    if _text_width(draw, text, font) <= max_width:
        return text
    ell = "…"
    cut = text
    while cut and _text_width(draw, cut + ell, font) > max_width:
        cut = cut[:-1]
    return (cut + ell) if cut else ell


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def _circular_avatar(avatar: Image.Image, size: int) -> Image.Image:
    avatar = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(avatar, (0, 0), _circle_mask(size))
    return out


def _round_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _gradient_bar(
    width: int,
    height: int,
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    radius: int,
) -> Image.Image:
    """Horizontal accent gradient clipped to a rounded rect."""
    if width <= 0 or height <= 0:
        return Image.new("RGBA", (max(width, 1), max(height, 1)), (0, 0, 0, 0))
    grad = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = grad.load()
    assert px is not None
    for x in range(width):
        t = x / max(width - 1, 1)
        r = _lerp(start[0], end[0], t)
        g = _lerp(start[1], end[1], t)
        b = _lerp(start[2], end[2], t)
        for y in range(height):
            px[x, y] = (r, g, b, 255)
    mask = _round_mask((width, height), radius)
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def _draw_rank_base(
    *,
    level: int,
    xp: float,
    target_xp: int,
    rank: int,
    total_members: int,
    display_name: str,
    accent: int,
    avatar_rgba: Image.Image,
) -> Image.Image:
    """Clean static rank card - solid PNG-safe layout, brand accent bar."""
    W, H = 934, 280
    progress = 0.0
    if target_xp and target_xp > 0:
        progress = max(0.0, min(float(xp) / float(target_xp), 1.0))

    ar, ag, ab = _hex_rgb(accent)
    
    er = _lerp(ar, 255, 0.28)
    eg = _lerp(ag, 255, 0.28)
    eb = _lerp(ab, 255, 0.28)

    
    canvas = Image.new("RGBA", (W, H), _CARD_BG)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    
    margin = 0
    draw.rounded_rectangle(
        (margin, margin, W - 1 - margin, H - 1 - margin),
        radius=24,
        fill=_CARD_PANEL,
    )

    
    strip = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strip)
    sd.rounded_rectangle((0, 18, 8, H - 19), radius=4, fill=(ar, ag, ab, 255))
    layer.alpha_composite(strip)

    
    sheen = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).rounded_rectangle(
        (12, 10, W - 13, 72),
        radius=18,
        fill=(ar, ag, ab, 22),
    )
    layer.alpha_composite(sheen)

    
    av_size = 148
    av = _circular_avatar(avatar_rgba, av_size)
    av_x, av_y = 36, (H - av_size) // 2
    ring_pad = 5
    ring_size = av_size + ring_pad * 2
    ring = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((1, 1, ring_size - 2, ring_size - 2), outline=(ar, ag, ab, 255), width=4)
    rd.ellipse((3, 3, ring_size - 4, ring_size - 4), outline=(255, 255, 255, 28), width=1)
    layer.paste(ring, (av_x - ring_pad, av_y - ring_pad), ring)
    layer.paste(av, (av_x, av_y), av)

    font_name = _load_font(34, bold=True)
    font_label = _load_font(15, bold=True)
    font_value = _load_font(22, bold=True)
    font_level = _load_font(52, bold=True)
    font_xp = _load_font(16, bold=False)
    font_small = _load_font(14, bold=False)

    text_left = av_x + av_size + 28
    bar_right = W - 40
    name_max = bar_right - text_left - 150

    name = _fit_text(draw, display_name, font_name, name_max)
    draw.text((text_left, 48), name, font=font_name, fill=_TEXT)

    
    rank_label = f"RANK #{int(rank)}"
    members_label = f"{int(total_members):,} ranked"
    draw.text((text_left, 96), rank_label, font=font_label, fill=(ar, ag, ab, 255))
    rw = _text_width(draw, rank_label, font_label)
    draw.text((text_left + rw + 12, 96), f"·  {members_label}", font=font_small, fill=_MUTED)

    
    lvl_title = "LEVEL"
    lvl_text = str(int(level))
    lt_w = _text_width(draw, lvl_title, font_small)
    lv_w = _text_width(draw, lvl_text, font_level)
    block_w = max(lt_w, lv_w)
    block_x = bar_right - block_w
    draw.text((block_x + (block_w - lt_w), 40), lvl_title, font=font_small, fill=_MUTED)
    draw.text((block_x + (block_w - lv_w), 58), lvl_text, font=font_level, fill=_TEXT)

    
    bar_x = text_left
    bar_y = 168
    bar_w = bar_right - text_left
    bar_h = 26
    radius = bar_h // 2

    
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=radius,
        fill=_TRACK,
    )

    fill_w = int(round(bar_w * progress))
    if progress > 0 and fill_w < radius * 2:
        fill_w = min(bar_w, radius * 2)
    if fill_w > 0:
        bar = _gradient_bar(fill_w, bar_h, (ar, ag, ab), (er, eg, eb), radius)
        layer.paste(bar, (bar_x, bar_y), bar)
        
        gloss_h = max(bar_h // 2, 4)
        gloss = Image.new("RGBA", (fill_w, gloss_h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gloss)
        gd.rounded_rectangle((0, 0, fill_w - 1, gloss_h - 1), radius=radius // 2, fill=(255, 255, 255, 40))
        layer.paste(gloss, (bar_x, bar_y + 2), gloss)

    
    cur = f"{int(xp):,}"
    need = f"{int(target_xp):,}"
    pct = f"{progress * 100:.1f}%"
    left_xp = f"{cur} / {need} XP"
    draw.text((bar_x, bar_y + bar_h + 12), left_xp, font=font_xp, fill=_SOFT)
    pct_w = _text_width(draw, pct, font_value)
    draw.text((bar_x + bar_w - pct_w, bar_y + bar_h + 8), pct, font=font_value, fill=_TEXT)

    canvas.alpha_composite(layer)
    
    rounded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded.paste(canvas, (0, 0), _round_mask((W, H), 24))
    return rounded


async def generate_rank_card(
    member,
    level: int,
    xp: float,
    target_xp: int,
    rank: int,
    total_members: int,
    *,
    accent: int | None = None,
) -> io.BytesIO:
    """Render a stable rank card PNG (static avatar frame - no broken GIFs)."""
    if accent is None:
        accent = int(getattr(bot_color, "base", 0xE1D2DE) or 0xE1D2DE)

    display_name = (
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or "User"
    )
    avatar_asset = getattr(member, "display_avatar", None)

    avatar_rgba: Image.Image
    try:
        
        if avatar_asset is not None:
            avatar_bytes = await avatar_asset.replace(format="png", size=256).read()
        else:
            raise RuntimeError("no avatar")
        with Image.open(io.BytesIO(avatar_bytes)) as src:
            avatar_rgba = src.convert("RGBA")
    except Exception:
        avatar_rgba = Image.new("RGBA", (256, 256), (70, 74, 96, 255))
        
        d = ImageDraw.Draw(avatar_rgba)
        d.ellipse((0, 0, 255, 255), fill=(54, 56, 70, 255))
        initial = (display_name[:1] or "?").upper()
        f = _load_font(96, bold=True)
        tw = _text_width(d, initial, f)
        d.text(((256 - tw) / 2, 64), initial, font=f, fill=_TEXT)

    card = _draw_rank_base(
        level=level,
        xp=xp,
        target_xp=target_xp,
        rank=rank,
        total_members=total_members,
        display_name=str(display_name),
        accent=int(accent),
        avatar_rgba=avatar_rgba,
    )

    buf = io.BytesIO()
    
    flat = Image.new("RGBA", card.size, _CARD_BG)
    flat.alpha_composite(card)
    flat.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    buf.name = "rank.png"  # type: ignore[attr-defined]
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


class Leveling(LevelingEvents, Package, metaclass=_Meta):
    """Server leveling with rank cards, multipliers, and role rewards."""

    def __init__(self, bot):
        Package.__init__(self, bot)
        LevelingEvents.__init__(self, bot)
        self.description = "Leveling system with rank cards, multipliers and rewards"
        self._xp_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def cog_load(self) -> None:
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
        if getattr(self.db, "pool", None) is not None:
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS message_rolegain TEXT DEFAULT NULL"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS channel_id BIGINT"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS stack BOOLEAN DEFAULT FALSE"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS command BOOLEAN DEFAULT FALSE"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS roles TEXT DEFAULT '[]'"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS channels TEXT DEFAULT '[]'"
                )
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "ALTER TABLE leveling ADD COLUMN IF NOT EXISTS users TEXT DEFAULT '[]'"
                )

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

    def _cfg_is_enabled(self, cfg: dict | None) -> bool:
        if not cfg:
            return False
        
        if "enabled" not in cfg:
            return True
        return bool(cfg.get("enabled"))

    async def _require_enabled(self, ctx) -> dict | None:
        cfg = await self._get_cfg(ctx.guild.id)
        if not cfg or not self._cfg_is_enabled(cfg):
            await ctx.warn(
                f"Not enabled\n> -# **use:** `{ctx.clean_prefix}leveling enable`"
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

    async def _level_replace(self, member: Member, params: str, *, level: int | None = None) -> str:
        row = await self.db.fetchrow(
            "SELECT * FROM level_user WHERE guild_id = $1 AND user_id = $2",
            member.guild.id,
            member.id,
        )
        lv = level if level is not None else (int(row["level"]) if row else 1)
        target = int(row["target_xp"]) if row else self._calc_target(lv)
        xp = float(row["xp"]) if row else 0.0
        return self._render_level_message(
            params,
            member=member,
            guild=member.guild,
            level=lv,
            xp=xp,
            target_xp=target,
        )

    
    
    

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
            return await ctx.warn("No rankings\n> -# **no one has ranked up yet**")
        sorted_rows = sorted(
            rows, key=lambda r: (r["level"], r["xp"]), reverse=True
        )
        position = next(
            (i + 1 for i, r in enumerate(sorted_rows) if r["user_id"] == member.id),
            None,
        )
        if position is None:
            return await ctx.warn(f"No data\n> -# **{member.mention}** has no recorded level data")
        data = next(r for r in sorted_rows if r["user_id"] == member.id)
        accent = int(getattr(self.bot, "color", None) or bot_color.base or 0xE1D2DE)
        card = await generate_rank_card(
            member if isinstance(member, Member) else ctx.author,
            int(data["level"]),
            float(data["xp"]),
            int(data["target_xp"]),
            position,
            len(sorted_rows),
            accent=accent,
        )
        return await ctx.send(file=File(fp=card, filename=f"rank-{member.id}.png"))

    
    
    

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
        aliases=["on"],
        description="Turn the leveling system on for this server",
        example=",leveling enable",
    )
    @has_permissions(manage_guild=True)
    async def leveling_enable(self, ctx):
        cfg = await self._get_cfg(ctx.guild.id)
        if cfg and self._cfg_is_enabled(cfg):
            return await ctx.warn("Already enabled\n> -# **leveling is already active**")
        if cfg:
            await self.db.execute(
                "UPDATE leveling SET enabled = TRUE WHERE guild_id = $1",
                ctx.guild.id,
            )
            return await ctx.success(
                "Leveling enabled\n> -# **status:** previous config and XP kept"
            )
        await self.db.execute(
            """INSERT INTO leveling
               (guild_id, message, multiplier, booster, stack, command, enabled)
               VALUES ($1, $2, 1.0, 1.0, false, false, true)""",
            ctx.guild.id,
            "Nice work {user.mention} - you reached **Level {level}**!",
        )
        return await ctx.success("Leveling enabled")

    @leveling.command(
        name="disable",
        aliases=["off"],
        description="Disable leveling without deleting configuration or XP",
        example=",leveling disable",
    )
    @has_permissions(manage_guild=True)
    async def leveling_disable(self, ctx):
        cfg = await self._get_cfg(ctx.guild.id)
        if not cfg:
            return await ctx.warn(
                f"Leveling is not configured\n> -# **use:** `{ctx.clean_prefix}leveling enable`"
            )
        if not self._cfg_is_enabled(cfg):
            return await ctx.warn(
                f"Already disabled\n> -# **use:** `{ctx.clean_prefix}leveling enable` to re-enable"
            )
        await self.db.execute(
            "UPDATE leveling SET enabled = FALSE WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success(
            "Leveling disabled\n"
            f"> -# **use:** `{ctx.clean_prefix}leveling wipe` to delete everything"
        )

    @leveling.command(
        name="channel",
        description="Set where level-up messages go (`any`, `dm`, or a channel)",
        example=",leveling channel #levels",
        usage="<channel or any or dm>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_channel(self, ctx, *, channel: str):
        if not await self._require_enabled(ctx):
            return
        raw = channel.strip().lower()
        if raw in {"any", "here", "current", "same"}:
            await self.db.execute(
                "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
                None,
                ctx.guild.id,
            )
            return await ctx.success(
                "Channel set\n> -# **destination:** same channel as message"
            )
        if raw in {"dm", "dms", "private"}:
            await self.db.execute(
                "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
                0,
                ctx.guild.id,
            )
            return await ctx.success("Channel set\n> -# **destination:** DMs")
        ch = None
        for converter in (
            commands.TextChannelConverter(),
            commands.ThreadConverter(),
        ):
            try:
                ch = await converter.convert(ctx, channel)
                break
            except Exception:
                continue
        if ch is None:
            return await ctx.warn("Invalid input\n> -# **use:** channel mention/ID, `any`, or `dm`")
        me = ctx.guild.me
        perms = ch.permissions_for(me) if me is not None else None
        if perms is not None and not perms.send_messages:
            return await ctx.warn(
                f"No permissions\n> -# **can't send messages in** {ch.mention}"
            )
        await self.db.execute(
            "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
            ch.id,
            ctx.guild.id,
        )
        return await ctx.success(f"Channel set\n> -# **destination:** {ch.mention}")

    @leveling.command(
        name="message",
        description=(
            "Set the level-up message script (embed/container/plain). "
            "Add `--rolegain` to make it a role reward message that only sends "
            "when the member gains a role from `,leveling rewards`"
        ),
        example=",leveling message Nice {user.mention} - Level {level}!",
        usage="<script or none> [--rolegain]",
    )
    @has_permissions(manage_guild=True)
    async def leveling_message(self, ctx, *, message: str = None):
        if not await self._require_enabled(ctx):
            return
        if message is None:
            return await ctx.send_help(ctx.command)
        raw = str(message)
        rolegain = False
        lines = raw.split("\n")
        kept_lines = []
        for line in lines:
            words = line.split()
            filtered = []
            for word in words:
                if word.lower() == "--rolegain":
                    rolegain = True
                else:
                    filtered.append(word)
            kept_lines.append(" ".join(filtered))
        script = "\n".join(kept_lines).strip()
        if not script:
            return await ctx.send_help(ctx.command)
        column = "message_rolegain" if rolegain else "message"
        if script.lower() == "none":
            await self.db.execute(
                f"UPDATE leveling SET {column} = $1 WHERE guild_id = $2",
                "none",
                ctx.guild.id,
            )
            return await ctx.success(
                "Message removed\n> -# **type:** level reward role message"
                if rolegain
                else "Message removed\n> -# **type:** level-up message"
            )
        await self.db.execute(
            f"UPDATE leveling SET {column} = $1 WHERE guild_id = $2",
            script,
            ctx.guild.id,
        )
        if rolegain:
            return await ctx.success(
                f"Message set\n> -# **type:** role reward message\n"
                f"> -# **sends when:** member gains a role from `{ctx.clean_prefix}leveling rewards`\n"
                f"```\n{script[:500]}\n```"
            )
        return await ctx.success(
            f"Message set\n> -# **sends to:** `{ctx.clean_prefix}leveling channel` destination\n"
            f"```\n{script[:500]}\n```"
        )

    @leveling.command(
        name="test",
        description="Preview the level-up message in the configured channel",
        example=",leveling test",
    )
    @has_permissions(manage_guild=True)
    async def leveling_test(self, ctx):
        cfg = await self._require_enabled(ctx)
        if not cfg:
            return
        script = cfg.get("message") or "none"
        if str(script).strip().lower() == "none":
            return await ctx.warn("No message\n> -# **no level-up message configured**")

        row = await self.db.fetchrow(
            "SELECT xp, level, target_xp FROM level_user WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        level = int(row["level"]) if row else 1
        xp = float(row["xp"]) if row else 0.0
        target = int(row["target_xp"]) if row else self._calc_target(level)

        dest = await self._resolve_level_destination(
            guild=ctx.guild,
            cfg=cfg,
            fallback=ctx.channel,
            member=ctx.author,
        )
        if dest is None:
            ch_id = cfg.get("channel_id")
            return await ctx.warn(
                f"Channel missing\n> -# **channel `{ch_id}` not found**\n"
                f"> -# **use:** `{ctx.clean_prefix}leveling channel #channel`"
            )

        msg = await self._send_level_message(
            dest,
            str(script),
            member=ctx.author,
            guild=ctx.guild,
            level=level,
            source_channel=ctx.channel,
            xp=xp,
            target_xp=target,
        )
        if msg is None:
            return await ctx.warn(
                "Failed to send\n> -# **check bot permissions in channel**"
            )
        jump = getattr(msg, "jump_url", None)
        if jump:
            return await ctx.success(f"Preview sent\n> -# {jump}")
        where = getattr(dest, "mention", None) or "DMs"
        return await ctx.success(f"Preview sent\n> -# **destination:** {where}")

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
                "Invalid multiplier\n> -# **must be one of:** "
                + ", ".join(f"`{m:.2f}`" for m in _VALID_MULTIS)
            )
        await self.db.execute(
            "UPDATE leveling SET multiplier = $1 WHERE guild_id = $2",
            float(multiplier),
            ctx.guild.id,
        )
        return await ctx.success(f"Multiplier set\n> -# **value:** {multiplier:.2f}")

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
                "Invalid multiplier\n> -# **must be one of:** "
                + ", ".join(f"`{m:.2f}`" for m in _VALID_MULTIS)
            )
        await self.db.execute(
            "UPDATE leveling SET booster = $1 WHERE guild_id = $2",
            float(multiplier),
            ctx.guild.id,
        )
        return await ctx.success(f"Booster multiplier set\n> -# **value:** {multiplier:.2f}")

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
            return await ctx.warn("Invalid level\n> -# **must be between 1 and 1000**")
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
            f"Level set\n> -# **{member.mention}** → Level {level}"
        )

    @leveling.command(
        name="reset",
        description="Reset a member's XP (or everyone with no member). This cannot be undone.",
        example=",leveling reset @user",
        usage="[member]",
    )
    @has_permissions(manage_guild=True)
    async def leveling_reset(self, ctx, member: Member = None):
        if not await self._get_cfg(ctx.guild.id):
            return await ctx.warn(
                f"Not configured\n> -# **use:** `{ctx.clean_prefix}leveling enable`"
            )
        view = ConfirmView(ctx.author.id)
        target = member.mention if member else "**everyone**"
        msg = await ctx.send(
            embed=Embed(
                color=0xED4245,
                description=(
                    f"{ctx.author.mention}: Reset level stats for {target}? "
                    "This action **cannot be undone**."
                ),
            ),
            view=view,
        )
        await view.wait()
        with contextlib.suppress(Exception):
            await msg.edit(view=None)
        if not view.value:
            return await ctx.warn("Cancelled\n> -# **reset was cancelled**")
        if member is None:
            await self.db.execute(
                "DELETE FROM level_user WHERE guild_id = $1", ctx.guild.id
            )
            return await ctx.success(
                "Stats reset\n> -# **target:** all members\n> -# **note:** this cannot be undone"
            )
        await self.db.execute(
            "DELETE FROM level_user WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            member.id,
        )
        return await ctx.success(
            f"Stats reset\n> -# **target:** {member.mention}\n> -# **note:** this cannot be undone"
        )

    @leveling.command(
        name="wipe",
        aliases=["deleteconfig", "purge"],
        description="Delete leveling configuration and all XP. This cannot be undone.",
        example=",leveling wipe",
    )
    @has_permissions(manage_guild=True)
    async def leveling_wipe(self, ctx):
        cfg = await self._get_cfg(ctx.guild.id)
        if not cfg:
            return await ctx.warn("Not configured\n> -# **leveling is not set up for this server**")
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send(
            embed=Embed(
                color=0xED4245,
                description=(
                    f"{ctx.author.mention}: Delete **all** leveling configuration and XP? "
                    "This action **cannot be undone**."
                ),
            ),
            view=view,
        )
        await view.wait()
        with contextlib.suppress(Exception):
            await msg.edit(view=None)
        if not view.value:
            return await ctx.warn("Cancelled\n> -# **wipe was cancelled**")
        await self.db.execute(
            "DELETE FROM leveling WHERE guild_id = $1", ctx.guild.id
        )
        await self.db.execute(
            "DELETE FROM level_user WHERE guild_id = $1", ctx.guild.id
        )
        with contextlib.suppress(Exception):
            await self.db.execute(
                "DELETE FROM level_rewards WHERE guild_id = $1", ctx.guild.id
            )
        with contextlib.suppress(Exception):
            await self.db.execute(
                "DELETE FROM level_multiplier WHERE guild_id = $1", ctx.guild.id
            )
        with contextlib.suppress(Exception):
            await self.db.execute(
                "DELETE FROM level_multiplier_voice WHERE guild_id = $1", ctx.guild.id
            )
        return await ctx.success(
            "Wiped\n> -# **config and XP deleted**\n> -# **note:** this cannot be undone"
        )

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
            return await ctx.warn("No rankings\n> -# **no ranked members yet**")
        sorted_rows = sorted(
            filtered, key=lambda r: (r["level"], r["xp"]), reverse=True
        )[:25]
        lines = []
        for i, r in enumerate(sorted_rows, 1):
            user = self.bot.get_user(r["user_id"]) or r["user_id"]
            lines.append(
                f"`#{i:02}` **{user}** - Level **{r['level']}** "
                f"(`{int(r['xp']):,}`/`{int(r['target_xp']):,}` XP)"
            )
        embed = Embed(
            title="Level Leaderboard",
            description="\n".join(lines),
            color=getattr(self.bot, "color", 0xE1D2DE) or 0xE1D2DE,
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
            getter = getattr(ctx.guild, "get_channel_or_thread", None)
            ch = getter(int(ch_id)) if callable(getter) else None
            if ch is None:
                ch = ctx.guild.get_channel(int(ch_id))
            ch_label = ch.mention if ch else f"`{ch_id}` (missing)"
        else:
            ch_label = "same channel (any)"
        embed = Embed(title="Leveling Config", color=0xE1D2DE)
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
        example=",leveling rewards add 10 @Legendary",
        usage="<level> <role>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_add(self, ctx, level: int, role: Role):
        if not await self._require_enabled(ctx):
            return
        if level < 1:
            return await ctx.warn("Invalid level\n> -# **must be at least 1**")
        existing = await self.db.fetchrow(
            "SELECT level FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        if existing:
            return await ctx.warn(
                f"Already exists\n> -# **{role.mention}** is already a reward for Level {existing['level']}"
            )
        await self.db.execute(
            "INSERT INTO level_rewards (guild_id, level, role_id) VALUES ($1, $2, $3)",
            ctx.guild.id,
            level,
            role.id,
        )
        return await ctx.success(
            f"Reward added\n> -# **{role.mention}** → Level {level}"
        )

    @leveling_rewards.command(
        name="remove",
        description="Remove a role reward",
        example=",leveling rewards remove @Legendary",
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
            return await ctx.warn(f"Not a reward\n> -# **{role.mention}** is not a level reward")
        await self.db.execute(
            "DELETE FROM level_rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        return await ctx.success(
            f"Reward removed\n> -# **level:** {row['level']}"
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
            return await ctx.warn("No rewards\n> -# **no level rewards configured**")
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            label = role.mention if role else f"`{r['role_id']}`"
            lines.append(f"{label} - **Level {r['level']}**")
        return await ctx.paginate(Embed(title="Level Rewards"), lines)

    @leveling_rewards.command(
        name="stack",
        description="Toggle stacking all reward roles vs highest only",
        example=",leveling rewards stack on",
        usage="<on or off>",
    )
    @has_permissions(manage_guild=True)
    async def leveling_rewards_stack(self, ctx, option: str):
        if not await self._require_enabled(ctx):
            return
        opt = option.strip().lower()
        if opt not in {"on", "off", "true", "false", "yes", "no", "1", "0"}:
            return await ctx.warn("Invalid option\n> -# **use:** `on` or `off`")
        enabled = opt in {"on", "true", "yes", "1"}
        await self.db.execute(
            "UPDATE leveling SET stack = $1 WHERE guild_id = $2",
            enabled,
            ctx.guild.id,
        )
        return await ctx.success(
            f"Stacking {'enabled' if enabled else 'disabled'}\n> -# **rewards:** {'all' if enabled else 'highest only'}"
        )

    

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
                return await ctx.warn(f"Already ignored\n> -# **{mention}** is already ignored")
            current.append(item_id)
            msg = f"Added\n> -# **{mention}** added to ignore list"
        else:
            if item_id not in current:
                return await ctx.warn(f"Not ignored\n> -# **{mention}** is not ignored")
            current.remove(item_id)
            msg = f"Removed\n> -# **{mention}** removed from ignore list"
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
        usage="<user or role or channel>",
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
        usage="<user or role or channel>",
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
            return await ctx.warn("Nothing ignored\n> -# **nothing is ignored for XP**")
        return await ctx.paginate(Embed(title="Level Ignore List"), lines)

    

    async def _sync_user_roles(self, guild, member: Member, user_level: int) -> None:
        cfg = await self._get_cfg(guild.id)
        if not cfg:
            return
        await self._apply_level_rewards(member, guild, cfg, user_level)


async def setup(bot) -> None:
    await bot.add_cog(Leveling(bot))
