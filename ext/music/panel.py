"""Now-playing panel art + interactive controls."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import aiohttp
import discord
from discord import ui
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

if TYPE_CHECKING:
    from . import Music

log = logging.getLogger("vain.music.panel")


def _fmt_ms(ms: int | float | None) -> str:
    try:
        total = max(0, int(ms or 0) // 1000)
    except Exception:
        total = 0
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    text = text or ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ell = "…"
    while text and draw.textlength(text + ell, font=font) > max_width:
        text = text[:-1]
    return (text + ell) if text else ell


async def fetch_image_bytes(url: str | None, *, timeout: float = 6.0) -> bytes | None:
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception:
        return None


def render_now_playing_card(
    *,
    title: str,
    artist: str,
    position_ms: int,
    length_ms: int,
    album_art: bytes | None = None,
    accent: int = 0x5865F2,
) -> bytes:
    """Aesthetic card: translucent album art bg, title, artist, dotted progress."""
    W, H = 900, 320
    pad = 36

    ar = (accent >> 16) & 255
    ag = (accent >> 8) & 255
    ab = accent & 255

    
    canvas = Image.new("RGBA", (W, H), (18, 18, 22, 255))

    
    if album_art:
        try:
            art = Image.open(io.BytesIO(album_art)).convert("RGBA")
            art = art.resize((W, H), Image.Resampling.LANCZOS)
            art = art.filter(ImageFilter.GaussianBlur(radius=22))
            art = ImageEnhance.Brightness(art).enhance(0.45)
            art.putalpha(110)
            canvas = Image.alpha_composite(canvas, art)
        except Exception:
            pass

    
    wash = Image.new("RGBA", (W, H), (ar, ag, ab, 28))
    canvas = Image.alpha_composite(canvas, wash)

    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(34, bold=True)
    artist_font = _load_font(22, bold=False)
    time_font = _load_font(18, bold=False)

    
    cover_size = 200
    cover_box = (pad, (H - cover_size) // 2, pad + cover_size, (H - cover_size) // 2 + cover_size)
    if album_art:
        try:
            cover = Image.open(io.BytesIO(album_art)).convert("RGBA")
            cover = cover.resize((cover_size, cover_size), Image.Resampling.LANCZOS)
            
            mask = Image.new("L", (cover_size, cover_size), 0)
            mdraw = ImageDraw.Draw(mask)
            mdraw.rounded_rectangle((0, 0, cover_size, cover_size), radius=22, fill=255)
            canvas.paste(cover, (cover_box[0], cover_box[1]), mask)
        except Exception:
            draw.rounded_rectangle(cover_box, radius=22, fill=(40, 40, 48, 200))
    else:
        draw.rounded_rectangle(cover_box, radius=22, fill=(40, 40, 48, 200))

    text_x = pad + cover_size + 28
    text_max = W - text_x - pad

    title_s = _fit_text(draw, title or "Unknown", title_font, text_max)
    artist_s = _fit_text(draw, artist or "Unknown", artist_font, text_max)

    draw.text((text_x, pad + 28), title_s, font=title_font, fill=(245, 245, 250, 255))
    draw.text((text_x, pad + 78), artist_s, font=artist_font, fill=(200, 200, 210, 230))

    
    bar_x1 = text_x
    bar_x2 = W - pad
    bar_y = H - pad - 48
    bar_h = 10

    pct = 0.0
    if length_ms and length_ms > 0:
        pct = max(0.0, min(1.0, float(position_ms) / float(length_ms)))

    
    track_col = (255, 255, 255, 45)
    draw.rounded_rectangle(
        (bar_x1, bar_y, bar_x2, bar_y + bar_h),
        radius=5,
        fill=track_col,
    )

    
    fill_w = int((bar_x2 - bar_x1) * pct)
    if fill_w > 4:
        draw.rounded_rectangle(
            (bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
            radius=5,
            fill=(ar, ag, ab, 240),
        )

    
    dot_r = 9
    dot_cx = bar_x1 + fill_w
    dot_cy = bar_y + bar_h // 2
    draw.ellipse(
        (dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r),
        fill=(255, 255, 255, 255),
        outline=(ar, ag, ab, 255),
        width=3,
    )

    
    left_t = _fmt_ms(position_ms)
    right_t = _fmt_ms(length_ms)
    draw.text((bar_x1, bar_y + 18), left_t, font=time_font, fill=(210, 210, 220, 220))
    tw = draw.textlength(right_t, font=time_font)
    draw.text(
        (bar_x2 - tw, bar_y + 18),
        right_t,
        font=time_font,
        fill=(210, 210, 220, 220),
    )

    
    label_font = _load_font(16, bold=False)
    draw.text((text_x, pad + 4), "NOW PLAYING", font=label_font, fill=(ar, ag, ab, 220))

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class AddTrackModal(ui.Modal, title="Add to queue"):
    query = ui.TextInput(
        label="Song name or playlist / track URL",
        style=discord.TextStyle.paragraph,
        placeholder="hold - jayden manis  ·  or a spotify/yt/apple link",
        required=True,
        max_length=400,
    )

    def __init__(self, on_submit: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]]):
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._on_submit(interaction, str(self.query.value).strip())


class MusicControlView(ui.View):
    """pause/resume · skip · stop · add · queue + select menu."""

    def __init__(self, cog: "Music", guild_id: int, *, paused: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.message: discord.Message | None = None
        self._paused = paused

        
        self.pause_btn.label = "resume" if paused else "pause"
        self.pause_btn.style = (
            discord.ButtonStyle.success if paused else discord.ButtonStyle.secondary
        )

        select = ui.Select(
            placeholder="More controls…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Skip",
                    value="skip",
                    description="Skip to the next track",
                    emoji="⏭",
                ),
                discord.SelectOption(
                    label="Stop",
                    value="stop",
                    description="Stop and leave voice",
                    emoji="⏹",
                ),
                discord.SelectOption(
                    label="Add song",
                    value="add",
                    description="Queue a song or playlist URL",
                    emoji="➕",
                ),
                discord.SelectOption(
                    label="Show queue",
                    value="queue",
                    description="View the queue (ephemeral)",
                    emoji="📜",
                ),
                discord.SelectOption(
                    label="Refresh panel",
                    value="refresh",
                    description="Update progress / art",
                    emoji="🔄",
                ),
            ],
            row=1,
        )
        select.callback = self._on_select
        self.add_item(select)

    def _player(self, inter: discord.Interaction):
        guild = inter.guild
        if guild is None:
            return None
        return guild.voice_client

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.guild is None or inter.guild.id != self.guild_id:
            return False
        member = inter.user
        if not isinstance(member, discord.Member):
            return False
        vc = self._player(inter)
        if vc is None or vc.channel is None:
            await inter.response.send_message("nothing playing", ephemeral=True)
            return False
        if not member.voice or member.voice.channel != vc.channel:
            await inter.response.send_message(
                "join the voice channel first", ephemeral=True
            )
            return False
        return True

    @ui.button(label="pause", style=discord.ButtonStyle.secondary, row=0)
    async def pause_btn(self, inter: discord.Interaction, button: ui.Button):
        player = self._player(inter)
        if player is None:
            return
        paused = bool(getattr(player, "is_paused", False))
        await player.set_pause(not paused)
        self._paused = not paused
        button.label = "resume" if self._paused else "pause"
        button.style = (
            discord.ButtonStyle.success if self._paused else discord.ButtonStyle.secondary
        )
        await inter.response.edit_message(view=self)
        await inter.followup.send(
            "paused" if self._paused else "resumed", ephemeral=True
        )

    @ui.button(label="skip", style=discord.ButtonStyle.primary, row=0)
    async def skip_btn(self, inter: discord.Interaction, button: ui.Button):
        player = self._player(inter)
        if player is None:
            return
        await inter.response.defer()
        try:
            await player.stop()
        except Exception:
            return
        await self.cog._play_next(self.guild_id, player, force=True)

    @ui.button(label="add", style=discord.ButtonStyle.secondary, row=0)
    async def add_btn(self, inter: discord.Interaction, button: ui.Button):
        async def _submit(i: discord.Interaction, query: str) -> None:
            await self.cog._panel_add_track(i, self.guild_id, query)

        await inter.response.send_modal(AddTrackModal(_submit))

    @ui.button(label="queue", style=discord.ButtonStyle.secondary, row=0)
    async def queue_btn(self, inter: discord.Interaction, button: ui.Button):
        await self.cog._panel_show_queue(inter, self.guild_id)

    @ui.button(label="stop", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, inter: discord.Interaction, button: ui.Button):
        player = self._player(inter)
        if player is None:
            return
        await self.cog._stop_and_leave(self.guild_id, player)
        try:
            await inter.response.edit_message(
                content=None,
                attachments=[],
                embed=discord.Embed(
                    color=0x2B2D31,
                    description="> stopped\n-# queue cleared",
                ),
                view=None,
            )
        except Exception:
            try:
                await inter.response.defer()
            except Exception:
                pass

    async def _on_select(self, inter: discord.Interaction) -> None:
        values = []
        data = inter.data or {}
        if isinstance(data, dict):
            values = list(data.get("values") or [])
        choice = values[0] if values else ""
        player = self._player(inter)

        if choice == "skip":
            if player is None:
                return await inter.response.send_message("nothing playing", ephemeral=True)
            await inter.response.defer()
            try:
                await player.stop()
            except Exception:
                return
            await self.cog._play_next(self.guild_id, player, force=True)
            return

        if choice == "stop":
            if player is None:
                return await inter.response.send_message("nothing playing", ephemeral=True)
            await self.cog._stop_and_leave(self.guild_id, player)
            await inter.response.edit_message(
                embed=discord.Embed(
                    color=0x2B2D31,
                    description="> stopped\n-# queue cleared",
                ),
                attachments=[],
                view=None,
            )
            return

        if choice == "add":
            async def _submit(i: discord.Interaction, query: str) -> None:
                await self.cog._panel_add_track(i, self.guild_id, query)

            await inter.response.send_modal(AddTrackModal(_submit))
            return

        if choice == "queue":
            await self.cog._panel_show_queue(inter, self.guild_id)
            return

        if choice == "refresh":
            await inter.response.defer()
            if player and getattr(player, "current", None):
                await self.cog._send_control_panel(
                    self.guild_id, player, player.current
                )
            return

        await inter.response.defer()
