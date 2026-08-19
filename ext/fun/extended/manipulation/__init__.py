from __future__ import annotations

import asyncio
import contextlib
import re
import os
import tempfile
import io
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont
from discord.ext import commands

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.managers.permissions import has_permissions
from config import color
from core.networks.media import ffmpeg as ffm
from core.tools import image_ops

if TYPE_CHECKING:
    from core.vain import Vain

FONT_PATH = str(Path(__file__).resolve().parents[4] / "var" / "caption.otf")


async def flux(ctx: Context, operation: str, attachment: discord.File, **payload) -> discord.File:
    data = attachment.fp.read()
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, "input.png")
        output_path = os.path.join(temp_dir, "output.gif")
        with open(input_path, "wb") as handle:
            handle.write(data)

        if operation == "caption" and "text" in payload:
            operation_str = f"caption[text={payload['text']}]"
        elif operation == "blur" and "radius" in payload:
            operation_str = f"blur[radius={payload['radius']}]"
        elif operation == "rotate" and "angle" in payload:
            operation_str = f"rotate[angle={payload['angle']}]"
        elif operation == "speed" and "factor" in payload:
            operation_str = f"speed[factor={payload['factor']}]"
        else:
            operation_str = operation

        process = await asyncio.create_subprocess_exec(
            "flux",
            "-i",
            input_path,
            "-o",
            operation_str,
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise commands.CommandError(stderr.decode() or "Flux processing failed")
        with open(output_path, "rb") as handle:
            return discord.File(BytesIO(handle.read()), filename=f"{operation}_result.gif")


class PartialAttachment(commands.Converter):
    @classmethod
    async def imageonly_fallback(cls, ctx: Context) -> discord.File:
        if ctx.message.attachments:
            return await ctx.message.attachments[0].to_file()
        if ctx.message.reference:
            message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if message.attachments:
                return await message.attachments[0].to_file()
        async for message in ctx.channel.history(limit=10):
            if message.attachments:
                return await message.attachments[0].to_file()
        raise commands.CommandError("No attachment provided")


def _quote_delete_emoji():
    try:
        from config import emojis
        return (
            getattr(emojis.paginator, "delete", None)
            or getattr(emojis.paginator, "cancel", None)
            or "<:delete:1535040504516055191>"
        )
    except Exception:
        return "<:delete:1535040504516055191>"


class _QuoteChannelView(discord.ui.View):
    """Guilt-style quote channel post: @user · Jump in content, Delete uses shared emoji."""

    def __init__(self, *, jump_url: str, author_id: int) -> None:
        super().__init__(timeout=None)
        self.author_id = author_id
        self.jump_url = jump_url
        btn = discord.ui.Button(
            label="Delete",
            style=discord.ButtonStyle.danger,
            emoji=_quote_delete_emoji(),
            custom_id=f"quote-delete:{author_id}",
        )
        btn.callback = self._delete_callback
        self.add_item(btn)

    async def _delete_callback(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        allowed = member.id == self.author_id
        if not allowed and isinstance(member, discord.Member):
            perms = member.guild_permissions
            allowed = bool(perms.manage_messages or perms.administrator)
        if not allowed:
            await interaction.response.send_message(
                "Only the person who quoted this (or staff with **Manage Messages**) can delete it.",
                ephemeral=True,
            )
            return
        with contextlib.suppress(Exception):
            await interaction.message.delete()
        if not interaction.response.is_done():
            with contextlib.suppress(Exception):
                await interaction.response.defer()


class Manipulation(Package):
    """Media manipulation commands."""

    async def _process(
        self,
        ctx: Context,
        attachment: discord.File,
        *,
        filename: str,
        processor: Callable[[bytes], Awaitable[bytes]],
        pil_fallback: Callable[[bytes], bytes] | None = None,
    ) -> None:
        async with ctx.typing():
            data = attachment.fp.read()
            try:
                result = await processor(data)
            except Exception:
                if pil_fallback is None:
                    return await ctx.fail("Failed to process image - install ffmpeg or attach a valid image")
                try:
                    result = pil_fallback(data)
                except Exception:
                    return await ctx.fail("Failed to process image - install ffmpeg or attach a valid image")
            await ctx.send(file=discord.File(BytesIO(result), filename=filename))

    async def _flux_command(
        self,
        ctx: Context,
        operation: str,
        *,
        pil_fallback: Callable[[bytes], bytes] | None = None,
        **payload,
    ) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, operation, attachment, **payload)
                await ctx.send(file=file)
            except Exception:
                if pil_fallback is None:
                    return await ctx.fail("Failed to process image - flux/ffmpeg unavailable for this effect")
                try:
                    data = attachment.fp.read()
                    result = pil_fallback(data)
                    await ctx.send(file=discord.File(BytesIO(result), filename=f"{operation}.png"))
                except Exception:
                    await ctx.fail("Failed to process image - flux/ffmpeg unavailable for this effect")

    @hybrid(name="media", description="apply effects to images and gifs", group=True, guild_only=True)
    async def media(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @media.command(name="spin", description="put a spin effect on an image")
    async def media_spin(self, ctx: Context) -> None:
        await self._flux_command(ctx, "spin")

    @media.command(name="rainbow", description="put a rainbow effect on an image")
    async def media_rainbow(self, ctx: Context) -> None:
        await self._flux_command(ctx, "rainbow")

    @media.command(name="deepfry", description="deep fry an image")
    async def media_deepfry(self, ctx: Context) -> None:
        await self._flux_command(ctx, "deepfry")

    @media.command(name="pixelate", description="pixelate an image")
    async def media_pixelate(self, ctx: Context) -> None:
        await self._flux_command(ctx, "pixelate", pil_fallback=image_ops.pil_pixelate)

    @media.command(name="caption", description="add a caption to an image")
    @describe(text="Caption text")
    async def media_caption(self, ctx: Context, *, text: str) -> None:
        await self._flux_command(
            ctx,
            "caption",
            text=text,
            pil_fallback=lambda data, t=text: image_ops.pil_caption(data, t, None),
        )

    @hybrid(
        name="caption",
        description="add a caption to the last image or gif in the channel",
        aliases=["cap"],
        guild_only=True,
    )
    @describe(text="Caption text, optionally with an image URL")
    async def caption(self, ctx: Context, *, text: str) -> None:
        if not text or not str(text).strip():
            return await ctx.warn(
                f"Provide caption text\n> -# **usage:** {ctx.cmd('caption your text')}"
            )
        raw = str(text).strip()
        source_url = None
        url_match = re.search(r"https?://\S+", raw)
        if url_match:
            source_url = url_match.group(0).rstrip(")>.,")
            raw = (raw[: url_match.start()] + raw[url_match.end() :]).strip()
        if not raw:
            return await ctx.warn("Provide caption text")

        data = None
        if ctx.message and ctx.message.attachments:
            att = ctx.message.attachments[0]
            name = (att.filename or "").lower()
            ctype = (att.content_type or "").lower()
            if ctype.startswith(("image/", "video/")) or name.endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
            ):
                data = await att.read()
        if data is None and ctx.message and ctx.message.reference:
            try:
                ref = ctx.message.reference.resolved
                if ref is None:
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if getattr(ref, "attachments", None):
                    data = await ref.attachments[0].read()
                elif source_url is None:
                    for embed in getattr(ref, "embeds", []) or []:
                        u = getattr(getattr(embed, "image", None), "url", None) or getattr(
                            getattr(embed, "thumbnail", None), "url", None
                        )
                        if u:
                            source_url = u
                            break
            except Exception:
                pass
        if data is None and source_url:
            data = await self._fetch_media_bytes(source_url)
        if data is None:
            data = await self._last_channel_image(ctx)

        if not data:
            return await ctx.warn("No image or gif found in this channel")

        async with ctx.typing():
            try:
                emoji_map = await image_ops.fetch_emoji_images(raw)
                result = await asyncio.to_thread(image_ops.pil_caption, data, raw, emoji_map)
            except Exception as exc:
                return await ctx.fail(f"Failed to caption that media\n> -# {exc}")
            await ctx.send(file=discord.File(BytesIO(result), filename="caption.gif"))

    async def _fetch_media_bytes(self, url: str) -> bytes | None:
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.read()
        except Exception:
            return None

    async def _last_channel_image(self, ctx: Context) -> bytes | None:
        if ctx.channel is None:
            return None
        skip_id = ctx.message.id if ctx.message else None
        try:
            async for msg in ctx.channel.history(limit=80):
                if skip_id and msg.id == skip_id:
                    continue
                for att in msg.attachments:
                    name = (att.filename or "").lower()
                    ctype = (att.content_type or "").lower()
                    if ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                        try:
                            return await att.read()
                        except Exception:
                            continue
                for embed in msg.embeds:
                    u = getattr(getattr(embed, "image", None), "url", None) or getattr(
                        getattr(embed, "thumbnail", None), "url", None
                    )
                    if u:
                        data = await self._fetch_media_bytes(u)
                        if data:
                            return data
        except Exception:
            return None
        return None

    @media.command(name="blur", description="blur an image")
    @describe(radius="Blur radius")
    async def media_blur(self, ctx: Context, radius: int = 5) -> None:
        await self._flux_command(
            ctx,
            "blur",
            radius=radius,
            pil_fallback=lambda data: image_ops.pil_blur(data, radius),
        )

    @media.command(name="grayscale", description="convert an image to grayscale")
    async def media_grayscale(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(
            ctx,
            attachment,
            filename="grayscale.png",
            processor=lambda d: ffm.image_to_gif(d, "format=gray"),
            pil_fallback=image_ops.pil_grayscale,
        )

    @media.command(name="invert", description="invert image colors")
    async def media_invert(self, ctx: Context) -> None:
        await self._flux_command(ctx, "invert", pil_fallback=image_ops.pil_invert)

    @media.command(name="reverse", description="reverse gif frames")
    async def media_reverse(self, ctx: Context) -> None:
        await self._flux_command(ctx, "reverse")

    @media.command(name="zoom", description="create a zoom effect")
    async def media_zoom(self, ctx: Context) -> None:
        await self._flux_command(ctx, "zoom")

    @media.command(name="speed", description="change gif speed")
    @describe(factor="Speed multiplier")
    async def media_speed(self, ctx: Context, factor: float = 2.0) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(
            ctx,
            attachment,
            filename="speed.gif",
            processor=lambda d: ffm.gif_speed(d, factor),
        )

    @media.command(name="rotate", description="rotate an image")
    @describe(angle="Rotation angle in degrees")
    async def media_rotate(self, ctx: Context, angle: int = 90) -> None:
        await self._flux_command(
            ctx,
            "rotate",
            angle=angle,
            pil_fallback=lambda data: image_ops.pil_rotate(data, angle),
        )

    @media.command(name="flip", description="flip an image vertically")
    async def media_flip(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="flip.gif", processor=lambda d: ffm.image_to_gif(d, "vflip"))

    @media.command(name="mirror", description="mirror an image horizontally")
    async def media_mirror(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="mirror.gif", processor=lambda d: ffm.image_to_gif(d, "hflip"))

    @media.command(name="sharpen", description="sharpen an image")
    async def media_sharpen(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="sharpen.gif", processor=lambda d: ffm.image_to_gif(d, "unsharp=5:5:1.0:5:5:0.0"))

    @media.command(name="brighten", description="brighten an image")
    async def media_brighten(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="brighten.gif", processor=lambda d: ffm.image_to_gif(d, "eq=brightness=0.15"))

    @media.command(name="contrast", description="increase image contrast")
    async def media_contrast(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="contrast.gif", processor=lambda d: ffm.image_to_gif(d, "eq=contrast=1.5"))

    @media.command(name="sepia", description="apply a sepia tone")
    async def media_sepia(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(
            ctx,
            attachment,
            filename="sepia.gif",
            processor=lambda d: ffm.image_to_gif(
                d,
                "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
            ),
        )

    @media.command(name="edges", description="detect edges in an image")
    async def media_edges(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="edges.gif", processor=lambda d: ffm.image_to_gif(d, "edgedetect"))

    @media.command(name="negate", description="negate image colors with ffmpeg")
    async def media_negate(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="negate.gif", processor=lambda d: ffm.image_to_gif(d, "negate"))

    @media.command(name="saturate", description="boost image saturation")
    async def media_saturate(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="saturate.gif", processor=lambda d: ffm.image_to_gif(d, "eq=saturation=2"))

    @media.command(name="fade", description="fade an image in")
    async def media_fade(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="fade.gif", processor=lambda d: ffm.image_to_gif(d, "fade=in:0:30"))

    @media.command(name="crop", description="crop to center square")
    async def media_crop(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="crop.gif", processor=lambda d: ffm.image_to_gif(d, "crop=min(iw\\,ih):min(iw\\,ih)"))

    @media.command(name="resize", description="resize an image")
    @describe(width="Target width", height="Target height")
    async def media_resize(self, ctx: Context, width: int = 320, height: int = 320) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        vf = f"scale={max(16, width)}:{max(16, height)}"
        await self._process(ctx, attachment, filename="resize.gif", processor=lambda d: ffm.image_to_gif(d, vf))


    def _quote_font(self, size: int):
        candidates = [
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            FONT_PATH,
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _quote_latin_font(self, size: int):
        """ASCII/Latin UI bits (@, em dash, vain brand) never use CJK fallback."""
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            FONT_PATH,
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _quote_body_font(self, text: str, size: int):
        """Latin body uses DejaVu; complex scripts use CJK-capable fonts."""
        needs_complex = False
        for ch in text or "":
            o = ord(ch)
            if o < 128:
                continue
            
            if o <= 0x024F or 0x1E00 <= o <= 0x1EFF:
                continue
            
            if 0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF:
                continue
            needs_complex = True
            break
        if needs_complex:
            return self._quote_font(size)
        return self._quote_latin_font(size)

    def _quote_mark_font(self, size: int):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            FONT_PATH,
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return self._quote_font(size)

    def _quote_wrap(self, text: str, font, max_width: int) -> list[str]:
        raw = (text or "").replace("\r", "")
        paragraphs = raw.split("\n") if "\n" in raw else [raw]
        lines: list[str] = []

        def _width(s: str) -> int:
            try:
                bb = font.getbbox(s)
                return max(0, bb[2] - bb[0])
            except Exception:
                return len(s) * max(1, getattr(font, "size", 12) // 2)

        for para in paragraphs:
            if not para and "\n" in raw:
                lines.append("")
                continue
            if not para:
                continue
            if " " in para or "\t" in para:
                tokens = para.replace("\t", " ").split()
                current = ""
                for word in tokens:
                    test = f"{current} {word}".strip() if current else word
                    if _width(test) <= max_width:
                        current = test
                        continue
                    if current:
                        lines.append(current)
                    if _width(word) <= max_width:
                        current = word
                        continue
                    chunk = ""
                    for ch in word:
                        t2 = chunk + ch
                        if _width(t2) <= max_width:
                            chunk = t2
                        else:
                            if chunk:
                                lines.append(chunk)
                            chunk = ch
                    current = chunk
                if current:
                    lines.append(current)
            else:
                current = ""
                for ch in para:
                    t2 = current + ch
                    if _width(t2) <= max_width:
                        current = t2
                    else:
                        if current:
                            lines.append(current)
                        current = ch
                if current:
                    lines.append(current)
        return lines or [""]


    def _quote_text_color(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b = rgb
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        if luma < 95:
            return (245, 245, 245)
        if luma > 230:
            return (max(r - 40, 30), max(g - 40, 30), max(b - 40, 30))
        return (r, g, b)

    def _quote_dominant_rgb(self, avatar: Image.Image) -> tuple[int, int, int]:
        try:
            from colorthief import ColorThief
            buf = io.BytesIO()
            avatar.convert("RGB").save(buf, format="PNG")
            buf.seek(0)
            ct = ColorThief(buf)
            dominant = ct.get_color(quality=1)
            try:
                palette = ct.get_palette(color_count=6, quality=1) or []
            except Exception:
                palette = []
            colors = [dominant, *palette]
            best = dominant
            best_score = -1.0
            for c in colors:
                if not c or len(c) < 3:
                    continue
                r, g, b = int(c[0]), int(c[1]), int(c[2])
                luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
                sat = max(r, g, b) - min(r, g, b)
                if luma < 25 or luma > 245:
                    continue
                score = sat * 1.4 + (130 - abs(luma - 140)) * 0.35
                if score > best_score:
                    best_score = score
                    best = (r, g, b)
            return (int(best[0]), int(best[1]), int(best[2]))
        except Exception:
            return (220, 220, 220)

    async def _generate_quote_image(
        self,
        content: str,
        display_name: str,
        username: str,
        avatar_url: str,
        avatar_bytes: bytes | None = None,
    ) -> bytes:
        """Guilt-inspired quote card: avatar fade + dominant-colour text."""
        loop = asyncio.get_running_loop()

        if avatar_bytes is None and avatar_url:
            try:
                timeout = aiohttp.ClientTimeout(total=12)
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/*,*/*;q=0.8",
                }
                async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                    async with session.get(str(avatar_url), allow_redirects=True) as resp:
                        if resp.status == 200:
                            avatar_bytes = await resp.read()
            except Exception:
                avatar_bytes = None

        emoji_map = await image_ops.fetch_emoji_images(content or "")

        def _build() -> bytes:
            W, H = 1000, 520
            AV_W = 480
            canvas = Image.new("RGB", (W, H), (0, 0, 0))

            if avatar_bytes:
                try:
                    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                except Exception:
                    avatar = Image.new("RGBA", (AV_W, H), (70, 70, 70, 255))
            else:
                avatar = Image.new("RGBA", (AV_W, H), (70, 70, 70, 255))

            side = max(avatar.size)
            square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ox = (side - avatar.size[0]) // 2
            oy = (side - avatar.size[1]) // 2
            square.paste(avatar, (ox, oy), avatar if avatar.mode == "RGBA" else None)
            avatar = square.resize((AV_W, H), Image.LANCZOS)

            dominant = self._quote_dominant_rgb(avatar)
            text_rgb = self._quote_text_color(dominant)
            mute_rgb = tuple(max(0, min(255, int(c * 0.55))) for c in text_rgb)

            fade = Image.new("L", (AV_W, H), 255)
            fade_draw = ImageDraw.Draw(fade)
            fade_start = int(AV_W * 0.42)
            for x in range(AV_W):
                if x < fade_start:
                    alpha = 255
                else:
                    t = (x - fade_start) / max(AV_W - fade_start, 1)
                    alpha = int(255 * (1.0 - t) ** 1.35)
                fade_draw.line([(x, 0), (x, H)], fill=alpha)
            avatar.putalpha(fade)

            base = Image.new("RGBA", (W, H), (0, 0, 0, 255))
            base.paste(avatar, (0, 0), avatar)
            canvas = base.convert("RGB")
            draw = ImageDraw.Draw(canvas)

            text_left = AV_W + 36
            text_right = W - 40
            max_text_w = text_right - text_left

            quote_font = self._quote_mark_font(110)
            body_size = 40
            attr_font = self._quote_latin_font(24)
            mark_font = self._quote_latin_font(18)

            clean = " ".join((content or "").split())
            if len(clean) > 320:
                clean = clean[:317].rstrip() + "..."

            body_font = self._quote_body_font(clean, body_size)
            emoji_size = max(18, int(body_size * 0.95))
            lines = image_ops.wrap_text_with_emojis(clean, body_font, max_text_w, emoji_map, emoji_size)
            while body_size > 22 and len(lines) > 7:
                body_size -= 2
                body_font = self._quote_body_font(clean, body_size)
                emoji_size = max(18, int(body_size * 0.95))
                lines = image_ops.wrap_text_with_emojis(clean, body_font, max_text_w, emoji_map, emoji_size)

            line_gap = int(body_size * 1.28)
            block_h = line_gap * len(lines)
            quote_mark = "“"
            qm_bbox = quote_font.getbbox(quote_mark)
            qm_h = qm_bbox[3] - qm_bbox[1]

            total_h = qm_h + 12 + block_h + 36 + 28
            top = max(36, (H - total_h) // 2)

            draw.text((text_left - 6, top - 8), quote_mark, fill=text_rgb, font=quote_font)

            y = top + qm_h + 4
            for line in lines:
                image_ops.measure_draw_emoji_line(
                    draw,
                    (text_left, y),
                    line,
                    body_font,
                    text_rgb,
                    emoji_map,
                    emoji_size,
                    draw_it=True,
                    canvas=canvas,
                    line_height=line_gap,
                )
                y += line_gap

            attr = f"\u2014  @{username}" if username else f"\u2014  {display_name}"
            draw.text((text_left, y + 18), attr, fill=mute_rgb, font=attr_font)

            brand = "vain"
            bb = mark_font.getbbox(brand)
            draw.text((W - (bb[2] - bb[0]) - 28, H - 34), brand, fill=(70, 70, 70), font=mark_font)

            out = io.BytesIO()
            canvas.save(out, format="PNG", optimize=True)
            return out.getvalue()

        return await loop.run_in_executor(None, _build)

    async def _ensure_quote_schema(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS quote_channels (
                guild_id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL
            )
            """
        )

    async def _get_quote_channel(self, guild_id: int):
        await self._ensure_quote_schema()
        row = await self.db.fetchrow(
            "SELECT channel_id FROM quote_channels WHERE guild_id = $1",
            guild_id,
        )
        if not row:
            return None
        return int(row["channel_id"] if isinstance(row, dict) else row[0])

    @hybrid(
        name="quote",
        description="quote a message as an image",
        aliases=["qm", "quotemessage"],
        group=True,
        invoke_without_command=True,
    )
    @describe(message="Message to quote (or reply to one)")
    async def quote_command(self, ctx: Context, message: discord.Message = None) -> None:
        if ctx.invoked_subcommand is not None:
            return
        if not message and ctx.message and ctx.message.reference:
            message = ctx.message.reference.resolved
        if not message or not isinstance(message, discord.Message):
            return await ctx.warn(
                f"Reply to a message or pass a message link\n> -# **usage:** {ctx.cmd('quote')} (reply)"
            )
        text = (message.content or "").strip()
        has_media = bool(message.attachments or message.stickers)
        has_rich = bool(message.embeds) or bool(getattr(message, "components", None))
        BOT_QUOTE = "Vain bot is so awesome it really is indeed the best bot ever 🤍"

        if not text:
            if message.author.bot:
                text = BOT_QUOTE
            elif has_media or has_rich:
                return await ctx.warn(
                    "Cute picture, but there's nothing to quote\n"
                    "> -# **I need actual text - images and embeds alone don't work**"
                )
            else:
                return await ctx.warn(
                    "That message is empty\n> -# **need some text to quote**"
                )

        async with ctx.typing():
            avatar_url = str(message.author.display_avatar.with_size(512).url)
            image_data = await self._generate_quote_image(
                text,
                message.author.display_name,
                message.author.name,
                avatar_url,
            )
            file = discord.File(io.BytesIO(image_data), filename="quote.gif")
            sent = await ctx.send(file=file)

            if ctx.guild is not None:
                dest_id = await self._get_quote_channel(ctx.guild.id)
                if dest_id:
                    dest = None
                    if ctx.guild:
                        dest = ctx.guild.get_channel_or_thread(dest_id)
                        if dest is None:
                            dest = ctx.guild.get_channel(dest_id)
                        if dest is None:
                            with contextlib.suppress(Exception):
                                dest = await ctx.guild.fetch_channel(dest_id)
                    
                    if dest is not None and hasattr(dest, "send"):
                        view = _QuoteChannelView(
                            jump_url=message.jump_url,
                            author_id=ctx.author.id,
                        )
                        
                        if dest.id == getattr(ctx.channel, "id", None):
                            pass
                        else:
                            try:
                                await dest.send(
                                    content=(
                                        f"-# **@{message.author.name}** · "
                                        f"[Jump to message]({message.jump_url})"
                                    ),
                                    file=discord.File(io.BytesIO(image_data), filename="quote.gif"),
                                    view=view,
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )
                            except Exception:
                                pass
            return sent

    @quote_command.group(
        name="channel",
        aliases=["set", "ch", "destination", "dest"],
        description="set the channel or thread where quotes are also posted",
        example=",quote channel #quotes",
        usage="[channel or thread]",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def quote_channel(self, ctx: Context, *, target: str = None) -> None:
        await self._ensure_quote_schema()
        
        if target is None or not str(target).strip():
            dest = ctx.channel
            if dest is None:
                return await ctx.warn("Couldn't resolve this channel")
            await self.db.execute(
                """
                INSERT INTO quote_channels (guild_id, channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET channel_id = EXCLUDED.channel_id
                """,
                ctx.guild.id,
                dest.id,
            )
            return await ctx.success(f"Quotes will also post in {dest.mention}")

        raw = str(target).strip()
        channel = None
        
        m = re.search(r"<#(\d+)>", raw)
        if m:
            cid = int(m.group(1))
            channel = ctx.guild.get_channel_or_thread(cid) if ctx.guild else None
        if channel is None and raw.isdigit():
            channel = ctx.guild.get_channel_or_thread(int(raw)) if ctx.guild else None
        if channel is None:
            with contextlib.suppress(Exception):
                channel = await commands.ThreadConverter().convert(ctx, raw)
        if channel is None:
            with contextlib.suppress(Exception):
                channel = await commands.TextChannelConverter().convert(ctx, raw)
        if channel is None:
            return await ctx.warn(
                "Provide a channel or thread\n"
                f"> -# **usage:** {ctx.cmd('quote channel #channel')} · "
                f"{ctx.cmd('quote channel')} sets it to here · "
                f"{ctx.cmd('quote channel reset')} to clear"
            )

        await self.db.execute(
            """
            INSERT INTO quote_channels (guild_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
        )
        return await ctx.success(f"Quotes will also post in {channel.mention}")

    @quote_channel.command(
        name="reset",
        aliases=["rem", "remove", "delete", "del", "clear", "off"],
        description="remove the quote destination channel",
        example=",quote channel reset",
    )
    @commands.has_permissions(manage_guild=True)
    async def quote_channel_reset(self, ctx: Context) -> None:
        await self._ensure_quote_schema()
        await self.db.execute(
            "DELETE FROM quote_channels WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success("Quote channel cleared")

    @hybrid(
        name="imagetogif",
        aliases=["img2gif", "togif", "image2gif"],
        description="convert an image to gif",
        guild_only=True,
    )
    async def imagetogif(self, ctx: Context) -> None:
        data = None
        filename = "image"
        if ctx.message and ctx.message.attachments:
            att = ctx.message.attachments[0]
            data = await att.read()
            filename = (att.filename or "image").rsplit(".", 1)[0]
        elif ctx.message and ctx.message.reference:
            try:
                ref = ctx.message.reference.resolved
                if ref is None:
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if getattr(ref, "attachments", None):
                    att = ref.attachments[0]
                    data = await att.read()
                    filename = (att.filename or "image").rsplit(".", 1)[0]
            except Exception:
                data = None
        if data is None:
            data = await self._last_channel_image(ctx)
            filename = "image"
        if not data:
            return await ctx.warn("No image provided or found")
        
        head = data[:6]
        if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
            return await ctx.warn("Already a GIF")
        async with ctx.typing():
            try:
                result = await asyncio.to_thread(image_ops.pil_to_gif, data)
            except Exception:
                return await ctx.fail("Failed to convert that image")
            await ctx.send(file=discord.File(BytesIO(result), filename=f"{filename}.gif"))


async def setup(bot: Vain):
    from .events import ManipulationEvents

    await bot.add_cog(Manipulation(bot))
    await bot.add_cog(ManipulationEvents(bot))
