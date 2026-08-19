from typing import Optional

from discord.ext.commands import group
from discord import Embed, TextChannel
from core.discord.package import Package
from core.discord.hybrid import hybrid, describe, command

from core.managers.permissions import has_permissions
from .settings import Settings


class ImgonlyCommands(Package):
    """image-only channel management"""

    async def _ensure_schema(self) -> None:
        await Settings.ensure_schema(self.db)

    async def cog_load(self) -> None:
        await self._ensure_schema()

    @command(
        name="imgonly",
        aliases=["gallery", "imageonly"],
        description="set up image + caption only channels",
        group=True,
    )
    async def imgonly(self, ctx):
        """imgonly help"""
        return await ctx.send_help()

    @imgonly.command(
        name="remove",
        aliases=["delete", "del"],
        description="remove a gallery channel (defaults to current channel)",
        example=",imageonly remove #img",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_remove(self, ctx, channel: Optional[TextChannel] = None):
        """un-gallery a channel"""
        await self._ensure_schema()
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.remove(channel.id)
        return await ctx.success(f"removed {channel.mention} from gallery channels")

    @imgonly.command(
        name="add",
        aliases=["create"],
        description="set a gallery channel (defaults to current channel)",
        example=",imageonly add #img",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_add(self, ctx, channel: Optional[TextChannel] = None):
        """make a gallery channel"""
        await self._ensure_schema()
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.add(channel.id)
        return await ctx.success(f"{channel.mention} is now a gallery channel")

    @imgonly.command(
        name="message",
        aliases=["script", "msg", "template"],
        description="set the custom message for a gallery channel",
        example=",imageonly message #img Only images allowed here!",
        usage="[channel] <message>",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_message(self, ctx, channel: Optional[TextChannel] = None, *, message: str = None):
        """set gallery channel message"""
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")

        settings = await Settings.fetch(self.bot, ctx.guild)
        if message is None:
            current = await settings.get_message(channel.id)
            if current:
                return await ctx.send(f"Current message for {channel.mention}:\n> {current}")
            return await ctx.warn(f"No custom message set for {channel.mention}")

        await settings.set_message(channel.id, message)
        return await ctx.success(f"Set message for {channel.mention}\n> {message}")

    @imgonly.command(
        name="list",
        description="view all gallery channels",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_list(self, ctx):
        """show gallery channels"""
        settings = await Settings.fetch(self.bot, ctx.guild)
        dead = []
        lines = []
        for row in settings.rows:
            cid = int(row["channel_id"])
            ch = ctx.guild.get_channel(cid)
            if not ch:
                dead.append(cid)
                continue
            lines.append(f"{ch.mention} (`{cid}`)")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        embed = Embed(title="Image Only Channels").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, numbered)
