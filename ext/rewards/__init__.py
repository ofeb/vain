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

from core.discord.mixin import _Meta
from core.discord.package import Package
from core.managers.permissions import has_permissions

from .events import LevelingEvents


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


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def _circular_avatar(avatar: Image.Image, size: int = 148) -> Image.Image:
    avatar = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(avatar, (0, 0), _circle_mask(size))
    return out


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


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
    """Static rank card frame + text + avatar (transparent outside rounded card)."""
    W, H = 900, 260
    progress = min(float(xp) / float(target_xp), 1.0) if target_xp > 0 else 0.0
    ar = (accent >> 16) & 0xFF
    ag = (accent >> 8) & 0xFF
    ab = accent & 0xFF

    
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)

    
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    _rounded_rect(pd, [0, 0, W - 1, H - 1], 28, (28, 30, 48, 255))
    
    for x in range(0, 220):
        alpha = int(50 * (1 - x / 220))
        pd.line([(x, 8), (x, H - 9)], fill=(ar, ag, ab, alpha))
    
    for y in range(H - 50, H - 1):
        t = (y - (H - 50)) / 50
        pd.line([(12, y), (W - 13, y)], fill=(ar, ag, ab, int(18 * t)))
    base.alpha_composite(panel)

    
    _rounded_rect(draw, [14, 28, 20, H - 28], 4, (ar, ag, ab, 220))

    
    av = _circular_avatar(avatar_rgba, 140)
    
    ring = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((1, 1, 148, 148), outline=(ar, ag, ab, 230), width=3)
    base.paste(ring, (40, (H // 2) - 75), ring)
    base.paste(av, (45, (H // 2) - 70), av)

    font_name = _load_font(32, bold=True)
    font_rank = _load_font(18, bold=True)
    font_level = _load_font(48, bold=True)
    font_xp = _load_font(17)
    font_small = _load_font(15)

    name = display_name
    if len(name) > 18:
        name = name[:17] + "…"
    draw.text((210, 42), name, font=font_name, fill=(245, 246, 252, 255))
    draw.text(
        (210, 88),
        f"RANK  #{rank}  ·  {total_members} members",
        font=font_rank,
        fill=(150, 154, 180, 255),
    )

    draw.text((W - 190, 36), "LEVEL", font=font_small, fill=(150, 154, 180, 255))
    lvl_text = str(level)
    try:
        lvl_w = draw.textlength(lvl_text, font=font_level)
    except Exception:
        lvl_w = 40
    draw.text((W - 48 - lvl_w, 50), lvl_text, font=font_level, fill=(255, 255, 255, 255))

    bar_x, bar_y, bar_w, bar_h = 210, 155, 560, 22
    _rounded_rect(draw, [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], 11, (42, 44, 62, 255))
    fill_w = max(int(bar_w * progress), 10 if progress > 0 else 0)
    if fill_w:
        _rounded_rect(
            draw,
            [bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
            11,
            (ar, ag, ab, 255),
        )
    pct = progress * 100
    draw.text(
        (bar_x, bar_y + 30),
        f"{int(xp):,}  /  {int(target_xp):,} XP   ·   {pct:.1f}%",
        font=font_xp,
        fill=(180, 184, 205, 255),
    )
    return base


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
    """Render a polished rank card. Animated avatars export as GIF."""
    display_name = getattr(member, "display_name", None) or getattr(member, "name", "User")
    avatar_asset = getattr(member, "display_avatar", None)
    is_animated = bool(getattr(avatar_asset, "is_animated", False))

    try:
        avatar_bytes = await avatar_asset.read()
        src = Image.open(io.BytesIO(avatar_bytes))
    except Exception:
        src = Image.new("RGBA", (180, 180), (70, 74, 96, 255))
        is_animated = False

    buf = io.BytesIO()

    if is_animated and getattr(src, "is_animated", False):
        frames: list[Image.Image] = []
        durations: list[int] = []
        n = min(getattr(src, "n_frames", 1), 48)  
        for i in range(n):
            try:
                src.seek(i)
                frame = src.convert("RGBA")
            except Exception:
                continue
            card = _draw_rank_base(
                level=level,
                xp=xp,
                target_xp=target_xp,
                rank=rank,
                total_members=total_members,
                display_name=display_name,
                accent=accent,
                avatar_rgba=frame,
            )
            
            frames.append(card.convert("RGBA"))
            durations.append(int(src.info.get("duration", 40) or 40))
        if not frames:
            is_animated = False
        else:
            
            bg_color = (22, 24, 38, 255)
            solid_frames = []
            for fr in frames:
                bg = Image.new("RGBA", fr.size, bg_color)
                bg.alpha_composite(fr)
                solid_frames.append(bg.convert("P", palette=Image.ADAPTIVE, colors=255))
            solid_frames[0].save(
                buf,
                format="GIF",
                save_all=True,
                append_images=solid_frames[1:],
                duration=durations[: len(solid_frames)],
                loop=0,
                optimize=True,
                disposal=2,
            )
            buf.seek(0)
            buf.name = "rank.gif"  # type: ignore[attr-defined]
            return buf

    
    if not isinstance(src, Image.Image):
        avatar_rgba = Image.new("RGBA", (180, 180), (70, 74, 96, 255))
    else:
        try:
            src.seek(0)
        except Exception:
            pass
        avatar_rgba = src.convert("RGBA")
    card = _draw_rank_base(
        level=level,
        xp=xp,
        target_xp=target_xp,
        rank=rank,
        total_members=total_members,
        display_name=display_name,
        accent=accent,
        avatar_rgba=avatar_rgba,
    )
    card.save(buf, format="PNG", optimize=True)
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
        ext = "gif" if getattr(card, "name", "").endswith(".gif") else "png"
        
        try:
            head = card.getvalue()[:6] if hasattr(card, "getvalue") else b""
            if head.startswith(b"GIF"):
                ext = "gif"
        except Exception:
            pass
        return await ctx.send(file=File(card, filename=f"rank-{member.id}.{ext}"))

    
    
    

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
        if raw in {"any", "here", "current", "same"}:
            await self.db.execute(
                "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
                None,
                ctx.guild.id,
            )
            return await ctx.success(
                "Level-ups will post in the **same channel** the member leveled in"
            )
        if raw in {"dm", "dms", "private"}:
            await self.db.execute(
                "UPDATE leveling SET channel_id = $1 WHERE guild_id = $2",
                0,
                ctx.guild.id,
            )
            return await ctx.success("Level-ups will be sent in **DMs**")
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
            return await ctx.warn("Use a channel mention/ID, `any`, or `dm`")
        me = ctx.guild.me
        perms = ch.permissions_for(me) if me is not None else None
        if perms is not None and not perms.send_messages:
            return await ctx.warn(
                f"I can't send messages in {ch.mention} — fix my permissions first"
            )
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
        return await ctx.success(
            f"Level-up message set — it will send to the configured "
            f"`{ctx.clean_prefix}leveling channel` destination.\n```\n{message[:500]}\n```"
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
            return await ctx.warn("No level-up message configured")

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
                f"Configured level channel `{ch_id}` is missing or not messageable. "
                f"Set it again with `{ctx.clean_prefix}leveling channel #channel`"
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
                "Failed to send the level-up preview — check bot permissions "
                "in the configured channel (and DMs if channel is `dm`)"
            )
        jump = getattr(msg, "jump_url", None)
        if jump:
            return await ctx.success(f"Sent preview → {jump}")
        where = getattr(dest, "mention", None) or "DMs"
        return await ctx.success(f"Sent preview → {where}")

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
            getter = getattr(ctx.guild, "get_channel_or_thread", None)
            ch = getter(int(ch_id)) if callable(getter) else None
            if ch is None:
                ch = ctx.guild.get_channel(int(ch_id))
            ch_label = ch.mention if ch else f"`{ch_id}` (missing)"
        else:
            ch_label = "same channel (any)"
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

    

    async def _sync_user_roles(self, guild, member: Member, user_level: int) -> None:
        cfg = await self._get_cfg(guild.id)
        if not cfg:
            return
        await self._apply_level_rewards(member, guild, cfg, user_level)


async def setup(bot) -> None:
    await bot.add_cog(Leveling(bot))
