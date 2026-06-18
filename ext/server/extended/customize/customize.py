from __future__ import annotations

from urllib.parse import urlparse

import aiohttp
import discord
from discord import Embed
from discord.ext.commands import group

from core.discord.package import Package

BIO_LINKS = ("https://bleed.bot/", "discord.gg/bleed")
BIO_MAX_LENGTH = 190
CLEAR_WORDS = {"clear", "none", "off", "remove", "reset"}


class CustomizeCommands(Package):
    """customize bot look in server"""

    async def _require_server_owner(self, ctx) -> bool:
        if ctx.guild is None:
            await ctx.warn("this command only works in **servers**")
            return False
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.warn("only the **server owner** can use this command")
            return False
        return True

    @staticmethod
    def _is_image_url(value: str) -> bool:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def _read_image_bytes(self, ctx, source: str | None) -> bytes | None:
        if not source:
            if not ctx.message.attachments:
                return None

            attachment = ctx.message.attachments[0]
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                await ctx.fail("uploaded file must be a **valid image**")
                return None
            return await attachment.read()

        if not self._is_image_url(source):
            await ctx.warn("provide a valid **http** or **https** image url")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(source) as response:
                    content_type = response.headers.get("content-type", "")
                    if response.status != 200:
                        await ctx.fail("failed to fetch that image")
                        return None
                    if "image/" not in content_type:
                        await ctx.fail("that url must point to a **valid image**")
                        return None
                    return await response.read()
        except (aiohttp.ClientError, ValueError):
            await ctx.fail("failed to fetch that image")
            return None

    def _normalized_bio(self, text: str) -> str:
        bio = text.strip()
        lower = bio.lower()
        if not any(link in lower for link in BIO_LINKS):
            bio = f"{bio}\nhttps://bleed.bot/"
        return bio

    @group(
        name="customize",
        aliases=["customization"],
        description="Customize the bot's appearance in your server",
        invoke_without_command=True,
    )
    async def customize(self, ctx):
        """show customize help"""
        if not await self._require_server_owner(ctx):
            return
        await ctx.send_help(ctx.command)

    @customize.command(
        name="name",
        aliases=["nick", "nickname"],
        description="Change the bot's nickname in the server",
        example=",customize name bleed",
    )
    async def customize_name(self, ctx, *, name: str = None):
        """change bot nickname"""
        if not await self._require_server_owner(ctx):
            return
        try:
            await ctx.guild.me.edit(
                nick=name,
                reason=f"nickname changed by {ctx.author}",
            )
            if name:
                await ctx.success(f"changed my name to **{name}**")
            else:
                await ctx.success("reset my server name")
        except discord.Forbidden:
            await ctx.warn("i don't have permission to change my **nickname**")
        except discord.HTTPException as e:
            await ctx.fail(f"failed to change nickname: `{e.text}`")

    @customize.command(
        name="avatar",
        aliases=["pfp", "av"],
        description="Change or reset the bot's server avatar",
        example=",customize avatar https://bleed.bot/avatar.png",
    )
    async def customize_avatar(self, ctx, source: str = None):
        """change bot server avatar"""
        if not await self._require_server_owner(ctx):
            return
        try:
            me = ctx.guild.me
            if source and source.lower() in CLEAR_WORDS:
                await me.edit(avatar=None)
                return await ctx.success("reset my server avatar")

            data = await self._read_image_bytes(ctx, source)
            if data is None:
                if not source and not ctx.message.attachments:
                    await ctx.warn("provide an image url or attachment")
                return

            await me.edit(avatar=data)
            return await ctx.success("updated my **server avatar**")
        except discord.Forbidden:
            await ctx.warn("i don't have permission to change my server avatar")
        except discord.HTTPException as e:
            await ctx.fail(f"failed to update server avatar: `{e.text}`")

    @customize.command(
        name="banner",
        description="Change or reset the bot's server banner",
        example=",customize banner https://bleed.bot/banner.png",
    )
    async def customize_banner(self, ctx, source: str = None):
        """change bot server banner"""
        if not await self._require_server_owner(ctx):
            return
        async with ctx.typing():
            try:
                me = ctx.guild.me
                if source and source.lower() in CLEAR_WORDS:
                    await me.edit(banner=None)
                    return await ctx.success("reset my server banner")

                data = await self._read_image_bytes(ctx, source)
                if data is None:
                    if not source and not ctx.message.attachments:
                        await ctx.warn("provide an image url or attachment")
                    return

                await me.edit(banner=data)
                return await ctx.success("updated my **server banner**")
            except discord.Forbidden:
                await ctx.warn("i lack permission to change my banner (may need more boosts)")
            except discord.HTTPException as e:
                await ctx.fail(f"failed to update server banner: `{e.text}`")

    @customize.command(
        name="bio",
        description="Change or reset the bot's server bio",
        example=",customize bio bleed is a really cool bot",
    )
    async def customize_bio(self, ctx, *, bio: str = None):
        """change bot server bio"""
        if not await self._require_server_owner(ctx):
            return
        try:
            me = ctx.guild.me
            if not bio:
                return await ctx.warn("provide a bio or say `none` to clear it")
            if bio.lower() in CLEAR_WORDS:
                await me.edit(bio=None)
                return await ctx.success("reset my bio")

            normalized = self._normalized_bio(bio)
            if len(normalized) > BIO_MAX_LENGTH:
                return await ctx.warn(
                    f"bio must stay under **{BIO_MAX_LENGTH}** characters after the bleed link is appended"
                )

            await me.edit(bio=normalized)
            e = Embed(
                color=self.color,
                description=f"{ctx.author.mention}: updated my bio: `{bio}`",
            )
            await ctx.reply(embed=e)
        except discord.HTTPException as e:
            await ctx.fail(f"failed to update bio: `{e.text}`")
