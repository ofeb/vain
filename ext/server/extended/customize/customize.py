from __future__ import annotations

import discord
from discord import Embed
from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class CustomizeCommands(Package):
    """customize bot look in server"""

    @group(
        name="customize",
        aliases=["customise"],
        description="Customize the bot's appearance in your server",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def customize(self, ctx):
        """show customize help"""
        await ctx.send_help(ctx.command)

    @customize.command(
        name="name",
        aliases=["nick", "nickname"],
        description="Change the bot's nickname in the server",
        example=",customize name bleed",
    )
    @has_permissions(manage_guild=True)
    async def customize_name(self, ctx, *, name: str = None):
        """change bot nickname"""
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
        aliases=["pfp", "icon"],
        description="Change or reset the bot's server avatar",
        example=",customize avatar none",
    )
    @has_permissions(manage_guild=True)
    async def customize_avatar(self, ctx, action: str = None):
        """change bot server avatar"""
        try:
            me = ctx.guild.me
            if action and action.lower() in ("none", "reset"):
                await me.edit(avatar=None)
                return await ctx.success("reset my server avatar")
            if not ctx.message.attachments:
                return await ctx.warn("upload an image or say `reset` to change my avatar")
            att = ctx.message.attachments[0]
            if not att.content_type or not att.content_type.startswith("image/"):
                return await ctx.fail("uploaded file must be a **valid image**")
            data = await att.read()
            await me.edit(avatar=data)
            e = Embed(color=self.color, description=f"{ctx.author.mention}: updated my **server avatar**")
            e.set_image(url=att.url)
            await ctx.reply(embed=e)
        except discord.Forbidden:
            await ctx.warn("i don't have permission to change my server avatar")
        except discord.HTTPException as e:
            await ctx.fail(f"failed to update server avatar: `{e.text}`")

    @customize.command(
        name="banner",
        description="Change or reset the bot's server banner",
        example=",customize banner none",
    )
    @has_permissions(manage_guild=True)
    async def customize_banner(self, ctx, action: str = None):
        """change bot server banner"""
        async with ctx.typing():
            try:
                me = ctx.guild.me
                if action and action.lower() in ("none", "reset"):
                    await me.edit(banner=None)
                    return await ctx.success("reset my server banner")
                if not ctx.message.attachments:
                    return await ctx.warn("upload an image or say `reset` to change my banner")
                att = ctx.message.attachments[0]
                if not att.content_type or not att.content_type.startswith("image/"):
                    return await ctx.warn("uploaded file must be a **valid image**")
                data = await att.read()
                await me.edit(banner=data)
                e = Embed(color=self.color, description=f"{ctx.author.mention}: updated my **server banner**")
                e.set_image(url=att.url)
                await ctx.reply(embed=e)
            except discord.Forbidden:
                await ctx.warn("i lack permission to change my banner (may need more boosts)")
            except discord.HTTPException as e:
                await ctx.fail(f"failed to update server banner: `{e.text}`")

    @customize.command(
        name="bio",
        aliases=["description"],
        description="Change or reset the bot's server bio",
        example=",customize bio bleed is a really cool bot",
    )
    @has_permissions(manage_guild=True)
    async def customize_bio(self, ctx, *, bio: str = None):
        """change bot server bio"""
        try:
            me = ctx.guild.me
            if not bio:
                return await ctx.warn("provide a bio or say `none` to clear it")
            if bio.lower() in ("none", "reset"):
                await me.edit(bio=None)
                return await ctx.success("reset my bio")
            await me.edit(bio=bio)
            e = Embed(
                color=self.color,
                description=f"{ctx.author.mention}: updated my bio: `{bio}`",
            )
            await ctx.reply(embed=e)
        except discord.HTTPException as e:
            await ctx.fail(f"failed to update bio: `{e.text}`")
