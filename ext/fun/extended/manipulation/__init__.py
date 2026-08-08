from __future__ import annotations

import asyncio
import os
import tempfile
from io import BytesIO
from typing import TYPE_CHECKING, Callable, Awaitable

import discord
from discord.ext import commands

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from config import color
from core.networks.media import ffmpeg as ffm
from core.tools import image_ops

if TYPE_CHECKING:
    from core.vain import Vain


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

    @hybrid(name="media", description="Apply effects to images and GIFs", group=True, guild_only=True)
    async def media(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @media.command(name="spin", description="Put a spin effect on an image")
    async def media_spin(self, ctx: Context) -> None:
        await self._flux_command(ctx, "spin")

    @media.command(name="rainbow", description="Put a rainbow effect on an image")
    async def media_rainbow(self, ctx: Context) -> None:
        await self._flux_command(ctx, "rainbow")

    @media.command(name="deepfry", description="Deep fry an image")
    async def media_deepfry(self, ctx: Context) -> None:
        await self._flux_command(ctx, "deepfry")

    @media.command(name="pixelate", description="Pixelate an image")
    async def media_pixelate(self, ctx: Context) -> None:
        await self._flux_command(ctx, "pixelate", pil_fallback=image_ops.pil_pixelate)

    @media.command(name="caption", description="Add a caption to an image")
    @describe(text="Caption text")
    async def media_caption(self, ctx: Context, *, text: str) -> None:
        await self._flux_command(ctx, "caption", text=text)

    @media.command(name="blur", description="Blur an image")
    @describe(radius="Blur radius")
    async def media_blur(self, ctx: Context, radius: int = 5) -> None:
        await self._flux_command(
            ctx,
            "blur",
            radius=radius,
            pil_fallback=lambda data: image_ops.pil_blur(data, radius),
        )

    @media.command(name="grayscale", description="Convert an image to grayscale")
    async def media_grayscale(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(
            ctx,
            attachment,
            filename="grayscale.png",
            processor=lambda d: ffm.image_to_gif(d, "format=gray"),
            pil_fallback=image_ops.pil_grayscale,
        )

    @media.command(name="invert", description="Invert image colors")
    async def media_invert(self, ctx: Context) -> None:
        await self._flux_command(ctx, "invert", pil_fallback=image_ops.pil_invert)

    @media.command(name="reverse", description="Reverse GIF frames")
    async def media_reverse(self, ctx: Context) -> None:
        await self._flux_command(ctx, "reverse")

    @media.command(name="zoom", description="Create a zoom effect")
    async def media_zoom(self, ctx: Context) -> None:
        await self._flux_command(ctx, "zoom")

    @media.command(name="speed", description="Change GIF speed")
    @describe(factor="Speed multiplier")
    async def media_speed(self, ctx: Context, factor: float = 2.0) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(
            ctx,
            attachment,
            filename="speed.gif",
            processor=lambda d: ffm.gif_speed(d, factor),
        )

    @media.command(name="rotate", description="Rotate an image")
    @describe(angle="Rotation angle in degrees")
    async def media_rotate(self, ctx: Context, angle: int = 90) -> None:
        await self._flux_command(
            ctx,
            "rotate",
            angle=angle,
            pil_fallback=lambda data: image_ops.pil_rotate(data, angle),
        )

    @media.command(name="flip", description="Flip an image vertically")
    async def media_flip(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="flip.gif", processor=lambda d: ffm.image_to_gif(d, "vflip"))

    @media.command(name="mirror", description="Mirror an image horizontally")
    async def media_mirror(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="mirror.gif", processor=lambda d: ffm.image_to_gif(d, "hflip"))

    @media.command(name="sharpen", description="Sharpen an image")
    async def media_sharpen(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="sharpen.gif", processor=lambda d: ffm.image_to_gif(d, "unsharp=5:5:1.0:5:5:0.0"))

    @media.command(name="brighten", description="Brighten an image")
    async def media_brighten(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="brighten.gif", processor=lambda d: ffm.image_to_gif(d, "eq=brightness=0.15"))

    @media.command(name="contrast", description="Increase image contrast")
    async def media_contrast(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="contrast.gif", processor=lambda d: ffm.image_to_gif(d, "eq=contrast=1.5"))

    @media.command(name="sepia", description="Apply a sepia tone")
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

    @media.command(name="edges", description="Detect edges in an image")
    async def media_edges(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="edges.gif", processor=lambda d: ffm.image_to_gif(d, "edgedetect"))

    @media.command(name="negate", description="Negate image colors with ffmpeg")
    async def media_negate(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="negate.gif", processor=lambda d: ffm.image_to_gif(d, "negate"))

    @media.command(name="saturate", description="Boost image saturation")
    async def media_saturate(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="saturate.gif", processor=lambda d: ffm.image_to_gif(d, "eq=saturation=2"))

    @media.command(name="fade", description="Fade an image in")
    async def media_fade(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="fade.gif", processor=lambda d: ffm.image_to_gif(d, "fade=in:0:30"))

    @media.command(name="crop", description="Crop to center square")
    async def media_crop(self, ctx: Context) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        await self._process(ctx, attachment, filename="crop.gif", processor=lambda d: ffm.image_to_gif(d, "crop=min(iw\\,ih):min(iw\\,ih)"))

    @media.command(name="resize", description="Resize an image")
    @describe(width="Target width", height="Target height")
    async def media_resize(self, ctx: Context, width: int = 320, height: int = 320) -> None:
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        vf = f"scale={max(16, width)}:{max(16, height)}"
        await self._process(ctx, attachment, filename="resize.gif", processor=lambda d: ffm.image_to_gif(d, vf))


async def setup(bot: Vain):
    from .events import ManipulationEvents

    await bot.add_cog(Manipulation(bot))
    await bot.add_cog(ManipulationEvents(bot))
