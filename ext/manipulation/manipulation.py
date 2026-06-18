from __future__ import annotations

import asyncio
import os
import tempfile
from io import BytesIO
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color

if TYPE_CHECKING:
    pass


async def flux(
    ctx: Context,
    operation: str,
    attachment: discord.File,
    **payload,
) -> discord.File:
    """Process image using flux command."""
    try:
        data = attachment.fp.read()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.png")
            output_path = os.path.join(temp_dir, "output.gif")

            with open(input_path, "wb") as f:
                f.write(data)

            if operation == "caption" and "text" in payload:
                operation_str = f"caption[text={payload['text']}]"
            elif operation == "blur" and "radius" in payload:
                operation_str = f"blur[radius={payload['radius']}]"
            elif operation == "rotate" and "angle" in payload:
                operation_str = f"rotate[angle={payload['angle']}]"
            else:
                operation_str = operation

            cmd = ["flux", "-i", input_path, "-o", operation_str, output_path]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise commands.CommandError(f"Flux processing failed: {stderr.decode()}")

            with open(output_path, "rb") as f:
                buffer = BytesIO(f.read())

            return discord.File(buffer, filename=f"{operation}_result.gif")

    except Exception as e:
        raise commands.CommandError("Failed to process image") from e


class PartialAttachment(commands.Converter):
    """Converter for image attachments."""

    async def convert(self, ctx: Context, argument: str) -> discord.File:
        try:
            member = await commands.MemberConverter().convert(ctx, argument)
            return await member.display_avatar.to_file()
        except Exception:
            pass

        if argument.startswith(("http://", "https://")):
            try:
                response = await ctx.bot.session.get(argument)
                buffer = BytesIO(await response.read())
                return discord.File(fp=buffer, filename="image.png")
            except Exception:
                raise commands.CommandError("Please provide a valid URL")

        raise commands.CommandError("Please provide a valid image or URL")

    @classmethod
    async def imageonly_fallback(cls, ctx: Context) -> discord.File:
        if len(ctx.message.attachments) > 0:
            return await ctx.message.attachments[0].to_file()
        elif ctx.message.reference:
            message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if len(message.attachments) > 0:
                return await message.attachments[0].to_file()
        else:
            async for message in ctx.channel.history(limit=10):
                if len(message.attachments) > 0:
                    return await message.attachments[0].to_file()
            else:
                raise commands.CommandError("No attachment provided")


class Manipulation(commands.Cog):
    """Media manipulation system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @group(
        name="media",
        description="Media manipulation commands",
        guild_only=True,
    )
    async def media(self, ctx: Context) -> None:
        """Media manipulation group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @media.command(
        name="spin",
        description="Put a spin effect on an image",
        guild_only=True,
    )
    async def spin(self, ctx: Context) -> None:
        """Put a spin effect on an image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "spin", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="rainbow",
        description="Put a rainbow effect on an image",
        guild_only=True,
    )
    async def rainbow(self, ctx: Context) -> None:
        """Put a rainbow effect on an image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "rainbow", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="deepfry",
        description="Deep fry an image",
        guild_only=True,
    )
    async def deepfry(self, ctx: Context) -> None:
        """Deep fry an image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "deepfry", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="pixelate",
        description="Create a pixelate effect from an image",
        guild_only=True,
    )
    async def pixelate(self, ctx: Context) -> None:
        """Create a pixelate effect from an image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "pixelate", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="caption",
        description="Put a caption on an image",
        guild_only=True,
    )
    @describe(text="Text for the caption")
    async def caption(self, ctx: Context, text: str) -> None:
        """Put a caption on an image."""
        if not text:
            await ctx.fail("Please provide text for the caption")
            return
        
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "caption", attachment, text=text)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="blur",
        description="Apply a blur effect to an image",
        guild_only=True,
    )
    @describe(radius="Blur radius")
    async def blur(self, ctx: Context, radius: int = 5) -> None:
        """Apply a blur effect to an image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "blur", attachment, radius=radius)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="grayscale",
        description="Convert image to grayscale",
        guild_only=True,
    )
    async def grayscale(self, ctx: Context) -> None:
        """Convert image to grayscale."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "grayscale", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="invert",
        description="Invert an image's colors",
        guild_only=True,
    )
    async def invert(self, ctx: Context) -> None:
        """Invert the colors of an image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "invert", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="reverse",
        description="Reverse the frames of a GIF",
        guild_only=True,
    )
    async def reverse(self, ctx: Context) -> None:
        """Reverse the frames of a GIF."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "reverse", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="zoom",
        description="Create a zoom effect with your image",
        guild_only=True,
    )
    async def zoom(self, ctx: Context) -> None:
        """Create a zoom effect with your image."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "zoom", attachment)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")

    @media.command(
        name="speed",
        description="Change the speed of a GIF",
        guild_only=True,
    )
    @describe(factor="Speed factor")
    async def speed(self, ctx: Context, factor: float = 2.0) -> None:
        """Change the speed of a GIF."""
        attachment = await PartialAttachment.imageonly_fallback(ctx)
        async with ctx.typing():
            try:
                file = await flux(ctx, "speed", attachment, factor=factor)
                await ctx.send(file=file)
            except Exception:
                await ctx.fail("Failed to process image")


async def setup(bot: commands.Bot):
    await bot.add_cog(Manipulation(bot))
